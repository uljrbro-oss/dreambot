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

        # keyboard listener state
        self._keys_down = set()
        try:
            from pynput import keyboard as _pyn_kb
            def _on_press(k):
                try:
                    ch = k.char
                except Exception:
                    ch = str(k)
                self._keys_down.add(str(ch))
            def _on_release(k):
                try:
                    ch = k.char
                except Exception:
                    ch = str(k)
                if str(ch) in self._keys_down:
                    self._keys_down.discard(str(ch))
            self._kb_listener = _pyn_kb.Listener(on_press=_on_press, on_release=_on_release)
            self._kb_listener.daemon = True
            self._kb_listener.start()
        except Exception:
            self._kb_listener = None

    def key_pressed(self, key_repr: str) -> bool:
        return str(key_repr) in self._keys_down

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

    # File operations
    def file_copy(self, src, dst):
        import shutil
        shutil.copy(src, dst)

    def file_delete(self, path):
        import os
        if os.path.exists(path):
            os.remove(path)

    def read_text(self, path):
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    def write_text(self, path, text):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(str(text))

    def get_file_list(self, pattern):
        import glob
        return glob.glob(pattern)

    # Clipboard
    def clipboard_set(self, text):
        try:
            import pyperclip
            pyperclip.copy(str(text))
            return True
        except Exception:
            # fallback: not available
            return False

    def clipboard_get(self):
        try:
            import pyperclip
            return pyperclip.paste()
        except Exception:
            return ''

    # HTTP
    def http_get(self, url, timeout=5.0):
        try:
            import requests
            r = requests.get(url, timeout=float(timeout))
            return r.text
        except Exception:
            return None

    # Window existence check (optional using pywinauto)
    def window_exists(self, title_substring):
        try:
            from pywinauto import Desktop
            ds = Desktop(backend='win32')
            wins = ds.windows()
            for w in wins:
                try:
                    if title_substring.lower() in w.window_text().lower():
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

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
        # build labels map and subroutines
        self.labels = {}
        self.subroutines = {}
        for i, ln in enumerate(self.lines):
            if '>' in ln:
                cmd = ln.split('>', 1)[0].strip()
            else:
                cmd = ln.strip()
            if cmd.upper().startswith('LABEL') or cmd.upper().startswith('SRT'):
                # format: Label>name or SRT>name
                try:
                    _, args = ln.split('>', 1)
                    name = args.strip()
                    self.labels[name] = i
                    # if SRT, find matching END>name
                    if cmd.upper().startswith('SRT'):
                        # scan forward
                        for j in range(i+1, len(self.lines)):
                            ln2 = self.lines[j]
                            if '>' in ln2:
                                cmd2 = ln2.split('>',1)[0].strip().upper()
                                if cmd2 == 'END':
                                    end_name = ln2.split('>',1)[1].strip()
                                    if end_name == name:
                                        self.subroutines[name] = (i, j)
                                        break
                except Exception:
                    pass

    def run(self, script_text: str):
        self._stop = False
        self.variables = {}
        self.parse(script_text)
        pc = 0
        repeat_stack = []  # tuples (varname, start_pc)

        # event handlers
        self.event_handlers = []
        self._event_thread = None
        self._event_thread_stop = threading.Event()

        def _start_event_thread():
            if self._event_thread and self._event_thread.is_alive():
                return
            self._event_thread_stop.clear()
            def _loop():
                last_states = [None] * 256
                while not self._event_thread_stop.is_set() and not self._stop:
                    for h in list(self.event_handlers):
                        try:
                            etype = h.get('type')
                            if etype == 'PIXEL_COLOR':
                                x, y = h.get('coord')
                                target = h.get('color')
                                rgb = self.runner_api.screenshot_getpixel(int(x), int(y))
                                val = (int(rgb[0]) << 16) | (int(rgb[1]) << 8) | int(rgb[2])
                                triggered = (val == target)
                            elif etype == 'FILE_EXISTS':
                                import os
                                fn = h.get('path')
                                triggered = os.path.exists(fn)
                            elif etype == 'KEY_DOWN':
                                key = h.get('key')
                                triggered = self.runner_api.key_pressed(key)
                            elif etype == 'CUSTOM':
                                varname = h.get('var')
                                triggered = bool(int(self.variables.get(varname, 0)))
                            else:
                                triggered = False
                        except Exception:
                            triggered = False
                        # rising edge
                        if h.get('_last', False) == False and triggered:
                            # fire subroutine
                            sub = h.get('sub')
                            if sub:
                                t = threading.Thread(target=lambda: self.run_subroutine(sub), daemon=True)
                                t.start()
                        h['_last'] = triggered
                    time.sleep(0.08)
            self._event_thread = threading.Thread(target=_loop, daemon=True)
            self._event_thread.start()

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
            elif cmd == 'FILECOPY':
                try:
                    src, dst = [p.strip() for p in args.split(',')[:2]]
                    self.runner_api.file_copy(src, dst)
                    self.log(f"FILECOPY {src} -> {dst}")
                except Exception as e:
                    self.log(f"FILECOPY error: {e}")
            elif cmd == 'FILEDELETE':
                try:
                    path = args.strip()
                    self.runner_api.file_delete(path)
                    self.log(f"FILEDELETE {path}")
                except Exception as e:
                    self.log(f"FILEDELETE error: {e}")
            elif cmd == 'READFILE':
                try:
                    path, varname = [p.strip() for p in args.split(',')[:2]]
                    text = self.runner_api.read_text(path)
                    self.variables[varname] = text
                    self.log(f"READFILE {path} -> {varname}")
                except Exception as e:
                    self.log(f"READFILE error: {e}")
            elif cmd == 'WRITEFILE':
                try:
                    path, text = [p.strip() for p in args.split(',', 1)[:2]]
                    self.runner_api.write_text(path, text)
                    self.log(f"WRITEFILE {path}")
                except Exception as e:
                    self.log(f"WRITEFILE error: {e}")
            elif cmd == 'GETFILELIST':
                try:
                    pattern, varname = [p.strip() for p in args.split(',')[:2]]
                    lst = self.runner_api.get_file_list(pattern)
                    self.variables[varname] = ';'.join(lst)
                    self.log(f"GETFILELIST {pattern} -> {varname} (count={len(lst)})")
                except Exception as e:
                    self.log(f"GETFILELIST error: {e}")
            elif cmd == 'CLIPSET':
                try:
                    text = args
                    ok = self.runner_api.clipboard_set(text)
                    self.log(f"CLIPSET ok={ok}")
                except Exception as e:
                    self.log(f"CLIPSET error: {e}")
            elif cmd == 'CLIPGET':
                try:
                    varname = args.strip()
                    v = self.runner_api.clipboard_get()
                    self.variables[varname] = v
                    self.log(f"CLIPGET {varname}")
                except Exception as e:
                    self.log(f"CLIPGET error: {e}")
            elif cmd == 'HTTPGET':
                try:
                    url, varname = [p.strip() for p in args.split(',')[:2]]
                    txt = self.runner_api.http_get(url)
                    self.variables[varname] = txt if txt is not None else ''
                    self.log(f"HTTPGET {url} -> {varname}")
                except Exception as e:
                    self.log(f"HTTPGET error: {e}")
            elif cmd == 'IFWINDOWOPEN':
                try:
                    title, varname = [p.strip() for p in args.split(',')[:2]]
                    exists = self.runner_api.window_exists(title)
                    self.variables[varname] = int(bool(exists))
                    self.log(f"IFWINDOWOPEN {title} -> {varname}={int(bool(exists))}")
                except Exception as e:
                    self.log(f"IFWINDOWOPEN error: {e}")
            elif cmd in ('WAITWINDOWOPEN', 'WWO'):
                try:
                    title, timeout, varname = [p.strip() for p in args.split(',')[:3]]
                    timeout = float(timeout)
                    found = False
                    start = time.time()
                    while not self._stop:
                        if self.runner_api.window_exists(title):
                            found = True
                            break
                        if timeout > 0 and (time.time() - start) >= timeout:
                            break
                        time.sleep(0.05)
                    if varname:
                        self.variables[varname] = int(found)
                    self.log(f"WWO found={found}")
                except Exception as e:
                    self.log(f"WWO error: {e}")
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
            elif cmd == 'ONEVENT' or cmd == 'ONE':
                try:
                    # OnEvent>EventType,EventParm,ExtraParm,Subroutine
                    parts = [p.strip() for p in args.split(',')]
                    etype = parts[0].upper() if parts else ''
                    parm1 = parts[1] if len(parts) > 1 else ''
                    parm2 = parts[2] if len(parts) > 2 else ''
                    sub = parts[3] if len(parts) > 3 else ''
                    if not sub:
                        # disable matching handler(s)
                        self.event_handlers = [h for h in self.event_handlers if h.get('sub') != sub]
                    else:
                        h = {'type': etype, 'sub': sub}
                        if etype == 'PIXEL_COLOR':
                            # parm1 is X:Y, parm2 is color
                            xstr, ystr = parm1.split(':')
                            h['coord'] = (int(xstr), int(ystr))
                            h['color'] = self._parse_color(parm2)
                        elif etype == 'FILE_EXISTS':
                            h['path'] = parm1
                        elif etype == 'KEY_DOWN':
                            h['key'] = parm1
                        elif etype == 'CUSTOM':
                            h['var'] = parm1
                        else:
                            # generic
                            h['parm1'] = parm1
                            h['parm2'] = parm2
                        h['_last'] = False
                        self.event_handlers.append(h)
                        _start_event_thread()
                    self.log(f"Registered OnEvent {etype} -> {sub}")
                except Exception as e:
                    self.log(f"OnEvent error: {e}")
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
        # stop event thread
        try:
            if self._event_thread:
                self._event_thread_stop.set()
        except Exception:
            pass
        self.log('Script finished')

    def run_subroutine(self, name: str):
        """Run the subroutine by name (lines between SRT>name and END>name)."""
        if name not in self.subroutines:
            self.log(f"Subroutine not found: {name}")
            return
        start, end = self.subroutines[name]
        # execute lines between start+1 .. end-1
        lines = self.lines[start+1:end]
        # simple executor similar to main loop but without event registration
        pc = 0
        while pc < len(lines) and not self._stop:
            ln = lines[pc]
            pc += 1
            if '>' in ln:
                cmd, args = ln.split('>', 1)
                cmd = cmd.strip().upper()
                args = args.strip()
            else:
                cmd = ln.strip().upper()
                args = ''
            for k, v in dict(self.variables).items():
                args = args.replace(f"%{k}%", str(v))
            if cmd == 'LET':
                if '=' in args:
                    name2, expr = args.split('=', 1)
                    name2 = name2.strip()
                    val = safe_eval_expr(expr.strip(), self.variables)
                    self.variables[name2] = int(val)
                    self.log(f"SRT LET {name2}={val}")
            elif cmd == 'MESSAGE':
                self.log(f"SRT {args}")
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
                except Exception as e:
                    self.log(f"SRT MouseMove error: {e}")
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
            else:
                self.log(f"SRT Unsupported MJT command: {cmd}")
        self.log(f"Subroutine {name} finished")

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


class MJTDebugger:
    """Line-by-line debugger for MJT scripts. Allows stepping and running with state inspection."""
    def __init__(self, log_fn=None, runner_api=None):
        self.log = log_fn or (lambda s: None)
        self.runner_api = runner_api or RunnerAPI()
        self.variables = {}
        self.lines = []
        self.pc = 0
        self._stop = False
        self._running = False
        self._thread = None

    def load(self, script_text: str):
        # simple parse (reuse interpreter parsing rules)
        self.lines = []
        for raw in script_text.splitlines():
            line = raw.rstrip('\n')
            if not line.strip():
                continue
            up = line.lstrip()
            if up.upper().startswith('REM') or line.strip().startswith(';'):
                continue
            self.lines.append(line.strip())
        self.variables = {}
        self.pc = 0
        self._stop = False
        self.breakpoints = set()
        # compute labels
        self.labels = {}
        self.subroutines = {}
        for i, ln in enumerate(self.lines):
            if '>' in ln:
                cmd = ln.split('>', 1)[0].strip().upper()
                args = ln.split('>', 1)[1].strip()
            else:
                cmd = ln.strip().upper(); args = ''
            if cmd == 'LABEL' or cmd == 'SRT':
                name = args
                self.labels[name] = i
            if cmd == 'SRT':
                # find matching END>name
                for j in range(i+1, len(self.lines)):
                    ln2 = self.lines[j]
                    if '>' in ln2:
                        cmd2 = ln2.split('>',1)[0].strip().upper()
                        if cmd2 == 'END':
                            end_name = ln2.split('>',1)[1].strip()
                            if end_name == args:
                                self.subroutines[args] = (i, j)
                                break
        self.log('Debugger loaded')

    def step(self):
        # pause if we're stopped or out of lines
        if self.pc >= len(self.lines) or self._stop:
            self.log('Debugger: no more lines or stopped')
            return False
        # breakpoint check
        if self.pc in getattr(self, 'breakpoints', set()):
            self.log(f"Debugger: hit breakpoint at line {self.pc+1}")
            self._stop = True
            return False
        line = self.lines[self.pc]
        # handle IF/GOTO special logic before advancing
        try:
            if '>' in line:
                cmd0, args0 = line.split('>', 1)
                cmd0 = cmd0.strip().upper()
                args0 = args0.strip()
            else:
                cmd0 = line.strip().upper(); args0 = ''
            # IF: if false, skip to ELSE/ENDIF
            if cmd0 == 'IF':
                # evaluate simple conditions like var=val
                cond = args0.strip()
                matched = False
                for op in ['<>', '>=', '<=', '>', '<', '=']:
                    if op in cond:
                        left, right = cond.split(op, 1)
                        left = left.strip(); right = right.strip()
                        lv = int(self.variables.get(left, 0)) if left.isidentifier() else int(left)
                        rv = int(right)
                        if op == '<>': matched = (lv != rv)
                        elif op == '>=': matched = (lv >= rv)
                        elif op == '<=': matched = (lv <= rv)
                        elif op == '>': matched = (lv > rv)
                        elif op == '<': matched = (lv < rv)
                        else: matched = (lv == rv)
                        break
                self.pc += 1
                if not matched:
                    depth = 0
                    while self.pc < len(self.lines):
                        ln = self.lines[self.pc]
                        self.pc += 1
                        cmd2 = ln.split('>',1)[0].strip().upper() if '>' in ln else ln.strip().upper()
                        if cmd2 == 'IF':
                            depth += 1
                        elif cmd2 == 'ENDIF':
                            if depth == 0:
                                break
                            else:
                                depth -= 1
                        elif cmd2 == 'ELSE' and depth == 0:
                            break
                    return True
                return True
            # GOTO: jump
            if cmd0 == 'GOTO':
                try:
                    label = args0.strip()
                    if label in getattr(self, 'labels', {}):
                        self.pc = self.labels[label] + 1
                        return True
                    else:
                        self.log(f"DBG GOTO: label not found: {label}")
                        self.pc += 1
                        return True
                except Exception as e:
                    self.log(f"DBG GOTO error: {e}")
                    self.pc += 1
                    return True
        except Exception:
            pass

        # normal step execution
        line = self.lines[self.pc]
        self.pc += 1
        try:
            if '>' in line:
                cmd, args = line.split('>', 1)
                cmd = cmd.strip().upper()
                args = args.strip()
            else:
                cmd = line.strip().upper()
                args = ''
            # substitute variables
            for k, v in dict(self.variables).items():
                args = args.replace(f"%{k}%", str(v))
            # support a small subset (LET, MESSAGE, WAIT small, MOUSEMOVE, LCLICK, GPC, WPC, IF/GOTO handled above)
            if cmd == 'LET' and '=' in args:
                name, expr = args.split('=', 1)
                name = name.strip()
                try:
                    val = safe_eval_expr(expr.strip(), self.variables)
                except Exception:
                    val = 0
                self.variables[name] = int(val)
                self.log(f"DBG LET {name}={val}")
            elif cmd == 'MESSAGE':
                self.log(f"DBG MSG: {args}")
            elif cmd == 'WAIT':
                try:
                    t = float(args.split(',')[0]) if args else 0.1
                except Exception:
                    t = 0.1
                endt = time.time() + float(t)
                while time.time() < endt and not self._stop:
                    time.sleep(0.05)
            elif cmd == 'MOUSEMOVE':
                try:
                    x, y = [int(p.strip()) for p in args.split(',')[:2]]
                    self.runner_api.move(x, y)
                    self.log(f"DBG MouseMove {x},{y}")
                except Exception as e:
                    self.log(f"DBG MouseMove error: {e}")
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
                    time.sleep(0.02)
                self.log(f"DBG LClick x{times}")
            elif cmd in ('GPC', 'GETPIXELCOLOR'):
                try:
                    x, y, varname = [p.strip() for p in args.split(',')[:3]]
                    x = int(x); y = int(y)
                    rgb = self.runner_api.screenshot_getpixel(x, y)
                    val = (int(rgb[0]) << 16) | (int(rgb[1]) << 8) | int(rgb[2])
                    self.variables[varname] = val
                    self.log(f"DBG GPC {varname}={val}")
                except Exception as e:
                    self.log(f"DBG GPC error: {e}")
            elif cmd in ('WPC', 'WAITPIXELCOLOR'):
                try:
                    parts = [p.strip() for p in args.split(',')]
                    color_token = parts[0]
                    x = int(parts[1]); y = int(parts[2])
                    timeout = float(parts[3]) if len(parts) > 3 else 0
                    if color_token.startswith('#'):
                        target = int(color_token.lstrip('#'), 16)
                    else:
                        target = int(color_token)
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
                    self.log(f"DBG WPC result: {bool(result)}")
                except Exception as e:
                    self.log(f"DBG WPC error: {e}")
            else:
                self.log(f"DBG Unsupported or unhandled: {line}")
        except Exception as e:
            self.log(f"DBG step error: {e}")
        return True

    def run(self):
        if self._running:
            return
        self._running = True
        self._stop = False
        def _runloop():
            while not self._stop and self.pc < len(self.lines):
                ok = self.step()
                if not ok:
                    break
            self._running = False
        self._thread = threading.Thread(target=_runloop, daemon=True)
        self._thread.start()

    def resume(self):
        # alias for run
        self.run()

    def pause(self):
        self._stop = True
        self._running = False

    def stop(self):
        self._stop = True
        self._running = False

    def toggle_breakpoint(self, line_index: int):
        if not hasattr(self, 'breakpoints'):
            self.breakpoints = set()
        if line_index in self.breakpoints:
            self.breakpoints.remove(line_index)
            self.log(f"Breakpoint removed: {line_index+1}")
        else:
            self.breakpoints.add(line_index)
            self.log(f"Breakpoint added: {line_index+1}")

    def list_breakpoints(self):
        if not hasattr(self, 'breakpoints'):
            return []
        return sorted([i+1 for i in self.breakpoints])

    def clear_breakpoints(self):
        if hasattr(self, 'breakpoints'):
            self.breakpoints.clear()

    def get_state(self):
        return {'pc': self.pc, 'variables': dict(self.variables), 'running': self._running, 'breakpoints': self.list_breakpoints()}

