"""mjt_runner.py

Core MJTNet-like interpreter (subset) for Macro Studio.
This module provides an MJTInterpreter class that parses simple MJT scripts
and executes them with a safe evaluator. It's designed to be testable and
extensible.

Supported subset (initial):
- LET var=expr
- MESSAGE text
- WAIT seconds
- MouseMove>x,y
- LClick or LClick * n
- GetPixelColor>X,Y,Var (GPC)
- WaitPixelColor>ColorCode,X,Y,Timeout (WPC)
- REPEAT>var and UNTIL>var,value
- EXIT / END

The interpreter can be passed a `runner_api` object to abstract pyautogui and other side effects
so tests can mock behavior easily.
"""

import ast
import threading
import time
from typing import List, Callable, Dict, Optional

# safe operator mapping
import operator as _operator

SAFE_OPERATORS = {
    ast.Add: _operator.add,
    ast.Sub: _operator.sub,
    ast.Mult: _operator.mul,
    ast.Div: _operator.floordiv,
    ast.Mod: _operator.mod,
    ast.Pow: _operator.pow,
    ast.USub: _operator.neg,
}


class EvalError(Exception):
    pass


def _safe_eval(node, variables: Dict[str, int]):
    if isinstance(node, ast.Num):
        return node.n
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return int(variables.get(node.id, 0))
    if isinstance(node, ast.BinOp):
        op = type(node.op)
        if op not in SAFE_OPERATORS:
            raise EvalError('Unsupported operator')
        left = _safe_eval(node.left, variables)
        right = _safe_eval(node.right, variables)
        return SAFE_OPERATORS[op](int(left), int(right))
    if isinstance(node, ast.UnaryOp):
        op = type(node.op)
        if op not in SAFE_OPERATORS:
            raise EvalError('Unsupported unary op')
        operand = _safe_eval(node.operand, variables)
        return SAFE_OPERATORS[op](int(operand))
    raise EvalError('Unsupported expression')


def safe_eval_expr(expr: str, variables: Dict[str, int]) -> int:
    try:
        node = ast.parse(expr, mode='eval').body
        return int(_safe_eval(node, variables))
    except Exception as e:
        raise EvalError(str(e))


class RunnerAPI:
    """Abstract runtime side-effect API. Default implementation uses pyautogui and OpenCV."""
    def __init__(self):
        try:
            import pyautogui
            self.pyautogui = pyautogui
        except Exception:
            self.pyautogui = None
        try:
            import cv2
            self.cv2 = cv2
        except Exception:
            self.cv2 = None

    def click(self, x=None, y=None):
        if self.pyautogui:
            if x is None or y is None:
                self.pyautogui.click()
            else:
                self.pyautogui.click(int(x), int(y))

    def move(self, x, y):
        if self.pyautogui:
            self.pyautogui.moveTo(int(x), int(y))

    def screenshot_getpixel(self, x, y):
        if self.pyautogui:
            return self.pyautogui.screenshot().getpixel((int(x), int(y)))
        return (0, 0, 0)

    def screenshot(self):
        """Return a numpy array screenshot in RGB format (H, W, 3)."""
        if self.pyautogui:
            return self.pyautogui.screenshot()
        return None

    def find_image(self, template_path, threshold=0.8):
        """Find template image on current screen. Returns center (x,y) or None."""
        if self.cv2 is None:
            return None
        try:
            import numpy as _np
            # get screenshot as numpy array (PIL Image)
            screen = self.screenshot()
            if screen is None:
                return None
            screen_arr = _np.array(screen)
            # convert PIL RGB to BGR for cv2
            screen_bgr = self.cv2.cvtColor(screen_arr, self.cv2.COLOR_RGB2BGR)
            tpl = self.cv2.imread(str(template_path))
            if tpl is None:
                return None
            res = self.cv2.matchTemplate(screen_bgr, tpl, self.cv2.TM_CCOEFF_NORMED)
            _, maxval, _, maxloc = self.cv2.minMaxLoc(res)
            if maxval >= float(threshold):
                h, w = tpl.shape[:2]
                return (int(maxloc[0] + w // 2), int(maxloc[1] + h // 2))
        except Exception:
            return None
        return None

class MJTInterpreter:
    def __init__(self, log_fn: Optional[Callable[[str], None]] = None, runner_api: Optional[RunnerAPI] = None):
        self.variables: Dict[str, int] = {}
        self.lines: List[str] = []
        self.labels: Dict[str, int] = {}
        self.log = log_fn or (lambda s: None)
        self.runner_api = runner_api or RunnerAPI()
        self._stop = False

    def stop(self):
        self._stop = True

    def parse(self, script_text: str):
        self.lines = []
        for raw in script_text.splitlines():
            line = raw.strip()
            if not line:
                continue
            # remove comments starting with ; or REM
            up = line.lstrip()
            if up.upper().startswith('REM') or line.startswith(';'):
                continue
            self.lines.append(line)
        # build labels map
        self.labels = {}
        for i, ln in enumerate(self.lines):
            if '>' in ln:
                cmd = ln.split('>', 1)[0].strip()
            else:
                cmd = ln.strip()
            if cmd.upper().startswith('LABEL') or cmd.upper().startswith('SRT'):
                # format: Label>name
                try:
                    _, args = ln.split('>', 1)
                    name = args.strip()
                    self.labels[name] = i
                except Exception:
                    pass

    def run(self, script_text: str):
        self._stop = False
        self.variables = {}
        self.parse(script_text)
        pc = 0
        repeat_stack = []  # tuples (varname, start_pc)
        while pc < len(self.lines) and not self._stop:
            line = self.lines[pc]
            pc += 1
            if '>' in line:
                cmd, args = line.split('>', 1)
                cmd = cmd.strip().upper()
                args = args.strip()
            else:
                cmd = line.strip().upper()
                args = ''
            # substitute %VAR% occurrences
            for k, v in dict(self.variables).items():
                args = args.replace(f"%{k}%", str(v))
            if cmd == 'LET':
                if '=' in args:
                    name, expr = args.split('=', 1)
                    name = name.strip()
                    val = safe_eval_expr(expr.strip(), self.variables)
                    self.variables[name] = int(val)
                    self.log(f"LET {name}={val}")
            elif cmd == 'MESSAGE':
                self.log(args)
            elif cmd == 'WAIT':
                try:
                    t = float(args.split(',')[0]) if args else 1.0
                except Exception:
                    t = 1.0
                endt = time.time() + float(t)
                while time.time() < endt and not self._stop:
                    time.sleep(0.05)
            elif cmd == 'MOUSEMOVE':
                try:
                    x, y = [int(p.strip()) for p in args.split(',')[:2]]
                    self.runner_api.move(x, y)
                    self.log(f"MouseMove {x},{y}")
                except Exception as e:
                    self.log(f"MouseMove error: {e}")
            elif cmd.startswith('LCLICK'):
                times = 1
                if '*' in args:
                    parts = args.split('*')
                    try:
                        times = int(parts[1].strip())
                    except Exception:
                        times = 1
                for _ in range(max(1, times)):
                    if self._stop:
                        break
                    self.runner_api.click()
                    time.sleep(0.05)
                self.log(f"LClick x{times}")
            elif cmd in ('GETPIXELCOLOR', 'GPC'):
                try:
                    x, y, varname = [p.strip() for p in args.split(',')[:3]]
                    x = int(x); y = int(y)
                    rgb = self.runner_api.screenshot_getpixel(x, y)
                    val = (int(rgb[0]) << 16) | (int(rgb[1]) << 8) | int(rgb[2])
                    self.variables[varname] = val
                    self.log(f"GPC {varname}={val}")
                except Exception as e:
                    self.log(f"GPC error: {e}")
            elif cmd == 'FINDIMAGEPOS':
                try:
                    # FINDIMAGEPOS>template_path,varx,vary
                    parts = [p.strip() for p in args.split(',')]
                    tpl = parts[0]
                    varx = parts[1] if len(parts) > 1 else None
                    vary = parts[2] if len(parts) > 2 else None
                    coords = self.runner_api.find_image(tpl)
                    if coords:
                        x, y = coords
                        if varx:
                            self.variables[varx] = int(x)
                        if vary:
                            self.variables[vary] = int(y)
                        self.log(f"FINDIMAGE found at {x},{y}")
                    else:
                        if varx:
                            self.variables[varx] = -1
                        if vary:
                            self.variables[vary] = -1
                        self.log("FINDIMAGE not found")
                except Exception as e:
                    self.log(f"FINDIMAGE error: {e}")
            elif cmd in ('WAITSCREENIMAGE', 'WSI'):
                try:
                    # WAITSCREENIMAGE>template_path,timeout,var
                    parts = [p.strip() for p in args.split(',')]
                    tpl = parts[0]
                    timeout = float(parts[1]) if len(parts) > 1 else 0
                    varname = parts[2] if len(parts) > 2 else None
                    found = False
                    start = time.time()
                    while not self._stop:
                        coords = self.runner_api.find_image(tpl)
                        if coords:
                            found = True
                            fx, fy = coords
                            self.variables['FOUND_X'] = int(fx)
                            self.variables['FOUND_Y'] = int(fy)
                            break
                        if timeout > 0 and (time.time() - start) >= float(timeout):
                            break
                        time.sleep(0.05)
                    if varname:
                        self.variables[varname] = int(found)
                    self.log(f"WSI found={found}")
                except Exception as e:
                    self.log(f"WSI error: {e}")
            elif cmd in ('WAITPIXELCOLOR', 'WPC'):
                try:
                    parts = [p.strip() for p in args.split(',')]
                    color_token = parts[0]
                    x = int(parts[1]); y = int(parts[2])
                    timeout = float(parts[3]) if len(parts) > 3 else 0
                    target = self._parse_color(color_token)
                    result = False
                    start = time.time()
                    while not self._stop:
                        rgb = self.runner_api.screenshot_getpixel(int(x), int(y))
                        val = (int(rgb[0]) << 16) | (int(rgb[1]) << 8) | int(rgb[2])
                        if val == target:
                            result = True
                            break
                        if timeout > 0 and (time.time() - start) >= float(timeout):
                            break
                        time.sleep(0.05)
                    self.variables['WPC_RESULT'] = int(result)
                    self.log(f"WPC result: {bool(result)}")
                except Exception as e:
                    self.log(f"WPC error: {e}")
            elif cmd == 'REPEAT':
                varname = args.strip()
                repeat_stack.append((varname, pc))
                if varname not in self.variables:
                    self.variables[varname] = 0
            elif cmd == 'UNTIL':
                try:
                    varname, value = [p.strip() for p in args.split(',')[:2]]
                    expected = int(value)
                    self.variables[varname] = int(self.variables.get(varname, 0))
                    if self.variables[varname] == expected:
                        if repeat_stack:
                            repeat_stack.pop()
                        else:
                            self.log('UNTIL without REPEAT')
                    else:
                        self.variables[varname] = int(self.variables.get(varname, 0)) + 1
                        if repeat_stack:
                            _, start_pc = repeat_stack[-1]
                            pc = start_pc
                        else:
                            self.log('UNTIL without REPEAT')
                except Exception as e:
                    self.log(f"UNTIL error: {e}")
            elif cmd == 'IF':
                # Simple conditional: support 'var=value', 'var<>value', 'var>value', 'var<value'
                try:
                    cond = args.strip()
                    matched = False
                    # find operator
                    for op in ['<>', '>=', '<=', '>', '<', '=']:
                        if op in cond:
                            left, right = cond.split(op, 1)
                            left = left.strip()
                            right = right.strip()
                            lv = int(self.variables.get(left, 0)) if left.isidentifier() else int(left)
                            rv = int(right)
                            if op == '<>':
                                matched = (lv != rv)
                            elif op == '>=':
                                matched = (lv >= rv)
                            elif op == '<=':
                                matched = (lv <= rv)
                            elif op == '>':
                                matched = (lv > rv)
                            elif op == '<':
                                matched = (lv < rv)
                            else:
                                matched = (lv == rv)
                            break
                    if not matched:
                        # skip to matching ELSE or ENDIF
                        depth = 0
                        while pc < len(self.lines):
                            ln = self.lines[pc]
                            pc += 1
                            cmd2 = ln.split('>', 1)[0].strip().upper() if '>' in ln else ln.strip().upper()
                            if cmd2 == 'IF':
                                depth += 1
                            elif cmd2 == 'ENDIF':
                                if depth == 0:
                                    break
                                else:
                                    depth -= 1
                            elif cmd2 == 'ELSE' and depth == 0:
                                break
                    # if matched, continue executing inner block
                except Exception as e:
                    self.log(f"IF error: {e}")
            elif cmd == 'ELSE':
                # skip to matching ENDIF
                depth = 0
                while pc < len(self.lines):
                    ln = self.lines[pc]
                    pc += 1
                    cmd2 = ln.split('>', 1)[0].strip().upper() if '>' in ln else ln.strip().upper()
                    if cmd2 == 'IF':
                        depth += 1
                    elif cmd2 == 'ENDIF':
                        if depth == 0:
                            break
                        else:
                            depth -= 1
                # continue after ENDIF
            elif cmd == 'ENDIF':
                # nothing to do; end of conditional block
                continue
            elif cmd == 'GOTO':
                try:
                    label = args.strip()
                    if label in self.labels:
                        # jump to the line after label
                        pc = self.labels[label] + 1
                    else:
                        self.log(f"GOTO: label not found: {label}")
                except Exception as e:
                    self.log(f"GOTO error: {e}")
            elif cmd in ('EXIT', 'END'):
                self.log('Script EXIT')
                break
            else:
                # labels and other commands ignored for now
                if cmd.startswith('LABEL') or cmd.startswith('SRT'):
                    continue
                self.log(f"Unsupported MJT command: {cmd}")
        self.log('Script finished')

    def _parse_color(self, token: str) -> int:
        token = token.strip()
        if token.startswith('#'):
            token = token.lstrip('#')
            if len(token) == 3:
                token = ''.join([c*2 for c in token])
            return int(token, 16)
        try:
            return int(token)
        except Exception:
            try:
                return int(token, 16)
            except Exception:
                raise ValueError('Invalid color code')
