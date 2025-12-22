# macro_app.py
# Simple GUI macro tool (prototype)
# Dependencies: PySide6, pyautogui, pynput, opencv-python, pillow, numpy

import sys
import time
import threading
import json
import tempfile
import os
from pathlib import Path

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QListWidget, QTextEdit, QLabel,
                               QFileDialog, QMessageBox, QInputDialog)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt5.QtGui import QPixmap, QImage, QColor, QGuiApplication

import pyautogui
from pynput import mouse, keyboard
from PIL import Image
import numpy as np
import cv2

pyautogui.FAILSAFE = True

APP_DIR = Path(__file__).parent
MACROS_DIR = APP_DIR / "macros"
MACROS_DIR.mkdir(exist_ok=True)


class Signals(QObject):
    update_actions = pyqtSignal()
    log = pyqtSignal(str)


class Recorder:
    def __init__(self, signals: Signals):
        self.signals = signals
        self.events = []
        self._running = False
        self._start_time = None
        self.mouse_listener = None
        self.keyboard_listener = None

    def start(self):
        if self._running:
            return
        self.events = []
        self._running = True
        self._start_time = time.time()

        def on_move(x, y):
            self.events.append({'t': time.time() - self._start_time, 'type': 'move', 'pos': (x, y)})

        def on_click(x, y, button, pressed):
            self.events.append({'t': time.time() - self._start_time, 'type': 'click', 'pos': (x, y), 'button': str(button), 'pressed': pressed})

        def on_scroll(x, y, dx, dy):
            self.events.append({'t': time.time() - self._start_time, 'type': 'scroll', 'pos': (x, y), 'dx': dx, 'dy': dy})

        def on_press(key):
            try:
                k = key.char
            except AttributeError:
                k = str(key)
            self.events.append({'t': time.time() - self._start_time, 'type': 'key', 'key': k, 'pressed': True})

        def on_release(key):
            try:
                k = key.char
            except AttributeError:
                k = str(key)
            self.events.append({'t': time.time() - self._start_time, 'type': 'key', 'key': k, 'pressed': False})

        self.mouse_listener = mouse.Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll)
        self.keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.mouse_listener.start()
        self.keyboard_listener.start()
        self.signals.log.emit("Recording started")

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self.mouse_listener:
            self.mouse_listener.stop()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        self.signals.log.emit(f"Recording stopped: {len(self.events)} events")

    def save(self, path: Path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.events, f, indent=2)

    def load(self, path: Path):
        with open(path, 'r', encoding='utf-8') as f:
            self.events = json.load(f)


class MacroPlayer:
    def __init__(self, signals: Signals):
        self.signals = signals
        self._running = False

    def play_events(self, events):
        def run():
            self._running = True
            t0 = None
            for ev in events:
                if not self._running:
                    break
                if t0 is None:
                    t0 = time.time() - ev.get('t', 0)
                delay = (t0 + ev.get('t', 0)) - time.time()
                if delay > 0:
                    time.sleep(delay)
                try:
                    if ev['type'] == 'move':
                        x, y = ev['pos']
                        pyautogui.moveTo(int(x), int(y))
                    elif ev['type'] == 'click':
                        x, y = ev['pos']
                        try:
                            # perform a real click at the location
                            pyautogui.click(int(x), int(y))
                        except Exception as e:
                            self.signals.log.emit(f"Click error: {e}")
                    elif ev['type'] == 'key':
                        k = ev['key']
                        if ev.get('pressed'):
                            try:
                                pyautogui.keyDown(k)
                            except Exception:
                                pyautogui.press(k)
                        else:
                            try:
                                pyautogui.keyUp(k)
                            except Exception:
                                pass
                except Exception as e:
                    self.signals.log.emit(f"Play error: {e}")
            self._running = False
            self.signals.log.emit("Playback finished")

        t = threading.Thread(target=run, daemon=True)
        t.start()

    def stop(self):
        self._running = False


# Image matching helper

def find_image_on_screen(template_path, threshold=0.8):
    screen = pyautogui.screenshot()
    screen = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
    tpl = cv2.imread(str(template_path))
    if tpl is None:
        return None
    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    _, maxval, _, maxloc = cv2.minMaxLoc(res)
    if maxval >= threshold:
        h, w = tpl.shape[:2]
        return (maxloc[0] + w // 2, maxloc[1] + h // 2)
    return None


# Color helpers

def color_distance(c1, c2):
    """Compute Euclidean distance between two RGB colors."""
    return ((int(c1[0]) - int(c2[0])) ** 2 + (int(c1[1]) - int(c2[1])) ** 2 + (int(c1[2]) - int(c2[2])) ** 2) ** 0.5


def color_matches(sample, target, tolerance=30):
    """Return True if sample color is within tolerance of target color."""
    try:
        return color_distance(sample, target) <= float(tolerance)
    except Exception:
        return False


# ---------- MJTNet script runner (subset) ----------
import ast
import operator as _operator

# safe operators mapping
SAFE_OPERATORS = {
    ast.Add: _operator.add,
    ast.Sub: _operator.sub,
    ast.Mult: _operator.mul,
    ast.Div: _operator.floordiv,
    ast.Mod: _operator.mod,
    ast.Pow: _operator.pow,
    ast.USub: _operator.neg,
}


def _safe_eval(node, variables):
    """Safely evaluate a simple arithmetic expression AST node, substituting variables."""
    if isinstance(node, ast.Num):
        return node.n
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return int(variables.get(node.id, 0))
    if isinstance(node, ast.BinOp):
        op = type(node.op)
        if op not in SAFE_OPERATORS:
            raise ValueError("Unsupported operator")
        left = _safe_eval(node.left, variables)
        right = _safe_eval(node.right, variables)
        return SAFE_OPERATORS[op](int(left), int(right))
    if isinstance(node, ast.UnaryOp):
        op = type(node.op)
        if op not in SAFE_OPERATORS:
            raise ValueError("Unsupported unary op")
        operand = _safe_eval(node.operand, variables)
        return SAFE_OPERATORS[op](int(operand))
    raise ValueError("Unsupported expression")


def safe_eval_expr(expr: str, variables: dict):
    try:
        node = ast.parse(expr, mode='eval').body
        return int(_safe_eval(node, variables))
    except Exception as e:
        raise ValueError(f"Expression eval error: {e}")


class MJTScriptRunner:
    """Run a small subset of MJTNet commands inside the app. Runs in its own thread."""
    def __init__(self, signals: Signals):
        self.signals = signals
        self.running = False
        self._stop = False

    def _parse_color(self, token: str):
        token = token.strip()
        if token.startswith('#'):
            token = token.lstrip('#')
            if len(token) == 3:
                token = ''.join([c*2 for c in token])
            return int(token, 16)
        try:
            return int(token)
        except Exception:
            # try hex without #
            try:
                return int(token, 16)
            except Exception:
                raise ValueError('Invalid color code')

    def stop(self):
        self._stop = True

    def run(self, script_text: str):
        self.running = True
        self._stop = False
        vars = {}
        lines = []
        for raw in script_text.splitlines():
            line = raw.strip()
            if not line:
                continue
            # strip comments (// or ; or REM or Remark)
            if line.upper().startswith(('REM', ';')):
                continue
            lines.append(line)

        pc = 0
        repeat_stack = []  # stack of (var_name, start_pc)
        try:
            while pc < len(lines) and not self._stop:
                line = lines[pc]
                pc += 1
                # split into cmd and args
                if '>' in line:
                    cmd, args = line.split('>', 1)
                    cmd = cmd.strip().upper()
                    args = args.strip()
                else:
                    cmd = line.strip().upper()
                    args = ''

                # substitute simple %VAR% occurrences in args
                for k, v in vars.items():
                    args = args.replace(f"%{k}%", str(v))

                # handle commands
                if cmd in ('LET', 'LET>') or cmd == 'LET':
                    # format: Let>k=0 or Let>k=k+1
                    if '=' in args:
                        name, expr = args.split('=', 1)
                        name = name.strip()
                        val = safe_eval_expr(expr.strip(), vars)
                        vars[name] = int(val)
                        self.signals.log.emit(f"LET {name}={val}")
                elif cmd == 'MESSAGE' or cmd == 'MESSAGE>':
                    self.signals.log.emit(args)
                elif cmd == 'WAIT' or cmd == 'WAIT>':
                    try:
                        t = float(args.split(',')[0]) if args else 1.0
                        self.signals.log.emit(f"WAIT {t}s")
                        # break sleep into small increments so stop is responsive
                        end = time.time() + t
                        while time.time() < end and not self._stop:
                            time.sleep(0.05)
                    except Exception as e:
                        self.signals.log.emit(f"WAIT parse error: {e}")
                elif cmd in ('MOUSEMOVE', 'MOUSEMOVE>'):
                    try:
                        x, y = [int(p.strip()) for p in args.split(',')[:2]]
                        pyautogui.moveTo(int(x), int(y))
                        self.signals.log.emit(f"MouseMove to {x},{y}")
                    except Exception as e:
                        self.signals.log.emit(f"MouseMove parse error: {e}")
                elif cmd in ('LCLICK', 'LCLICK>','LCL'):
                    # supports LClick * n and LClick normally
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
                        pyautogui.click()
                        time.sleep(0.05)
                    self.signals.log.emit(f"LClick x{times}")
                elif cmd in ('GETPIXELCOLOR', 'GPC'):
                    try:
                        x, y, varname = [p.strip() for p in args.split(',')[:3]]
                        x = int(x); y = int(y)
                        rgb = pyautogui.screenshot().getpixel((int(x), int(y)))
                        val = (int(rgb[0]) << 16) | (int(rgb[1]) << 8) | int(rgb[2])
                        vars[varname] = val
                        self.signals.log.emit(f"GPC {varname}={val}")
                    except Exception as e:
                        self.signals.log.emit(f"GPC error: {e}")
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
                            rgb = pyautogui.screenshot().getpixel((int(x), int(y)))
                            val = (int(rgb[0]) << 16) | (int(rgb[1]) << 8) | int(rgb[2])
                            if val == target:
                                result = True
                                break
                            if timeout > 0 and (time.time() - start) >= float(timeout):
                                break
                            time.sleep(0.05)
                        vars['WPC_RESULT'] = int(result)
                        self.signals.log.emit(f"WPC result: {bool(result)}")
                    except Exception as e:
                        self.signals.log.emit(f"WPC error: {e}")
                elif cmd == 'REPEAT':
                    # Repeat>var
                    varname = args.strip()
                    repeat_stack.append((varname, pc))
                    # ensure var exists
                    if varname not in vars:
                        vars[varname] = 0
                elif cmd == 'UNTIL':
                    # Until>var,value  or Until>var,operator,value? Support equality only for now
                    try:
                        varname, value = [p.strip() for p in args.split(',')[:2]]
                        expected = int(value)
                        vars[varname] = int(vars.get(varname, 0))
                        if vars[varname] == expected:
                            # pop stack
                            if repeat_stack:
                                repeat_stack.pop()
                            else:
                                self.signals.log.emit('UNTIL without REPEAT')
                        else:
                            # increment var and jump back
                            vars[varname] = int(vars.get(varname, 0)) + 1
                            if repeat_stack:
                                _, start_pc = repeat_stack[-1]
                                pc = start_pc
                            else:
                                self.signals.log.emit('UNTIL without REPEAT')
                    except Exception as e:
                        self.signals.log.emit(f"UNTIL error: {e}")
                elif cmd in ('EXIT', 'END'):
                    self.signals.log.emit('Script requested EXIT')
                    break
                elif cmd == 'MESSAGE' or cmd == 'MESSAGE>':
                    self.signals.log.emit(args)
                else:
                    self.signals.log.emit(f"Unsupported MJT command: {cmd}")
        except Exception as e:
            self.signals.log.emit(f"MJT script error: {e}")
        finally:
            self.running = False
            self.signals.log.emit('MJT script finished')


class ColorPicker(QWidget):
    """A small floating color picker that shows the color under the cursor and emits a signal when a color is picked."""
    color_picked = pyqtSignal(int, int, tuple)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Color Picker")
        self.setWindowFlags(self.windowFlags() | Qt.Tool)
        self.resize(260, 140)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.swatch = QLabel()
        self.swatch.setFixedSize(64, 64)
        self.info = QLabel('Move cursor to sample color')
        top.addWidget(self.swatch)
        top.addWidget(self.info)
        layout.addLayout(top)

        btn_row = QHBoxLayout()
        self.btn_pick = QPushButton('Pick Color')
        self.btn_pick_any = QPushButton('Pick Anywhere')
        self.btn_copy = QPushButton('Copy HEX')
        btn_row.addWidget(self.btn_pick)
        btn_row.addWidget(self.btn_pick_any)
        btn_row.addWidget(self.btn_copy)
        layout.addLayout(btn_row)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_preview)
        self.timer.start(100)

        self.btn_pick.clicked.connect(self.pick)
        self.btn_pick_any.clicked.connect(self.start_pick_any)
        self.btn_copy.clicked.connect(self.copy_hex)

        # listeners used for pick-anywhere mode
        self._mouse_listener = None
        self._keyboard_listener = None

    def start_pick_any(self):
        """Hide the picker and wait for a global mouse click to pick the color at that location.
        Press Esc to cancel."""
        QMessageBox.information(self, "Pick Anywhere", "The picker will hide. Click anywhere on the screen to capture the color, or press Esc to cancel.")
        # hide the picker so it doesn't get in the way
        self.hide()

        def on_click(x, y, button, pressed):
            if pressed:
                try:
                    rgb = pyautogui.screenshot().getpixel((int(x), int(y)))
                except Exception:
                    rgb = (0, 0, 0)
                # finish pick on the GUI thread via signal
                try:
                    self._finish_pick(x, y, rgb)
                except Exception:
                    pass
                return False  # stop listener

        def on_press(key):
            try:
                if key == keyboard.Key.esc:
                    try:
                        self._cancel_pick()
                    except Exception:
                        pass
                    return False
            except Exception:
                pass

        self._mouse_listener = mouse.Listener(on_click=on_click)
        self._keyboard_listener = keyboard.Listener(on_press=on_press)
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def _finish_pick(self, x, y, rgb):
        # stop listeners if still running
        try:
            if self._mouse_listener:
                self._mouse_listener.stop()
        except Exception:
            pass
        try:
            if self._keyboard_listener:
                self._keyboard_listener.stop()
        except Exception:
            pass
        # show picker and emit
        self.show()
        self.update_preview()
        self.color_picked.emit(int(x), int(y), tuple(rgb))
        self.info.setText(f'Picked at {x},{y}  RGB: {rgb}  HEX: #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}')

    def _cancel_pick(self):
        try:
            if self._mouse_listener:
                self._mouse_listener.stop()
        except Exception:
            pass
        try:
            if self._keyboard_listener:
                self._keyboard_listener.stop()
        except Exception:
            pass
        self.show()
        self.info.setText('Pick cancelled')

    def closeEvent(self, e):
        try:
            if getattr(self, '_mouse_listener', None):
                self._mouse_listener.stop()
        except Exception:
            pass
        try:
            if getattr(self, '_keyboard_listener', None):
                self._keyboard_listener.stop()
        except Exception:
            pass
        self.timer.stop()
        return super().closeEvent(e)

    def update_preview(self):
        x, y = pyautogui.position()
        try:
            rgb = pyautogui.screenshot().getpixel((int(x), int(y)))
        except Exception:
            rgb = (0, 0, 0)
        pix = QPixmap(64, 64)
        pix.fill(QColor(*rgb))
        self.swatch.setPixmap(pix)
        self.info.setText(f'Pos: {x},{y}  RGB: {rgb}  HEX: #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}')

    def pick(self):
        x, y = pyautogui.position()
        try:
            rgb = pyautogui.screenshot().getpixel((int(x), int(y)))
        except Exception:
            rgb = (0, 0, 0)
        self.color_picked.emit(int(x), int(y), tuple(rgb))

    def copy_hex(self):
        txt = self.info.text()
        if 'HEX:' in txt:
            hexpart = txt.split('HEX:')[-1].strip()
            QGuiApplication.clipboard().setText(hexpart)


class MacroApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Macro Studio (prototype)")
        self.resize(900, 600)

        self.signals = Signals()
        self.signals.update_actions.connect(self.refresh_actions)
        self.signals.log.connect(self.log)

        self.recorder = Recorder(self.signals)
        self.player = MacroPlayer(self.signals)

        self.actions = []  # list of dict actions
        self._playing = False
        self._stop_playback = False
        self._play_thread = None

        # UI
        main = QHBoxLayout(self)

        left = QVBoxLayout()
        btn_row = QHBoxLayout()
        self.btn_record = QPushButton("Record")
        self.btn_stop = QPushButton("Stop")
        self.btn_play = QPushButton("Play")
        btn_row.addWidget(self.btn_record)
        btn_row.addWidget(self.btn_stop)
        btn_row.addWidget(self.btn_play)
        left.addLayout(btn_row)

        self.list_actions = QListWidget()
        left.addWidget(self.list_actions)

        action_row = QHBoxLayout()
        self.btn_add_delay = QPushButton("Add Delay")
        self.btn_add_move_click = QPushButton("Add Move+Click")
        self.btn_add_color = QPushButton("Color Clicker")
        self.btn_color_picker = QPushButton("Open Color Picker")
        self.btn_add_image = QPushButton("Add Image Click")
        action_row.addWidget(self.btn_add_delay)
        action_row.addWidget(self.btn_add_move_click)
        action_row.addWidget(self.btn_add_color)
        action_row.addWidget(self.btn_color_picker)
        action_row.addWidget(self.btn_add_image)
        left.addLayout(action_row)

        save_row = QHBoxLayout()
        self.btn_save_macro = QPushButton("Save Macro")
        self.btn_load_macro = QPushButton("Load Macro")
        self.btn_export = QPushButton("Export JSON")
        self.btn_run_mjt = QPushButton("Run MJT Script")
        save_row.addWidget(self.btn_save_macro)
        save_row.addWidget(self.btn_load_macro)
        save_row.addWidget(self.btn_export)
        save_row.addWidget(self.btn_run_mjt)
        left.addLayout(save_row)

        main.addLayout(left, 2)

        right = QVBoxLayout()
        self.editor = QTextEdit()
        right.addWidget(QLabel("Action editor (select item then edit JSON):"))
        right.addWidget(self.editor)
        editor_btns = QHBoxLayout()
        self.btn_update = QPushButton("Update Action")
        self.btn_delete = QPushButton("Delete Action")
        self.btn_move_up = QPushButton("Move Up")
        self.btn_move_down = QPushButton("Move Down")
        editor_btns.addWidget(self.btn_update)
        editor_btns.addWidget(self.btn_delete)
        editor_btns.addWidget(self.btn_move_up)
        editor_btns.addWidget(self.btn_move_down)
        right.addLayout(editor_btns)

        right.addWidget(QLabel("Log:"))
        self.logbox = QTextEdit()
        self.logbox.setReadOnly(True)
        right.addWidget(self.logbox)

        main.addLayout(right, 3)

        # Connect
        self.btn_record.clicked.connect(self.on_record)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_play.clicked.connect(self.on_play)
        self.list_actions.itemSelectionChanged.connect(self.on_select_action)

        self.btn_add_delay.clicked.connect(self.add_delay_action)
        self.btn_add_move_click.clicked.connect(self.add_move_click_action)
        self.btn_add_color.clicked.connect(self.add_color_action)
        self.btn_color_picker.clicked.connect(self.open_color_picker)
        self.btn_add_image.clicked.connect(self.add_image_action)

        self.btn_save_macro.clicked.connect(self.save_macro)
        self.btn_load_macro.clicked.connect(self.load_macro)
        self.btn_export.clicked.connect(self.export_json)
        self.btn_run_mjt.clicked.connect(self.run_mjt_script)
        # Script Editor and Event Manager
        self.btn_script_editor = QPushButton("Script Editor")
        self.btn_event_manager = QPushButton("Event Manager")
        save_row.addWidget(self.btn_script_editor)
        save_row.addWidget(self.btn_event_manager)
        self.btn_script_editor.clicked.connect(self.open_script_editor)
        self.btn_event_manager.clicked.connect(self.open_event_manager)

        self.btn_update.clicked.connect(self.update_action)
        self.btn_delete.clicked.connect(self.delete_action)
        self.btn_move_up.clicked.connect(self.move_action_up)
        self.btn_move_down.clicked.connect(self.move_action_down)

        # expose script controls
        self.btn_stop.clicked.connect(self.stop_script)

    def log(self, msg: str):
        self.logbox.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def on_record(self):
        self.recorder.start()

    def on_stop(self):
        # stop recorder if running
        self.recorder.stop()
        # stop playback if running
        if getattr(self, '_playing', False):
            self._stop_playback = True
            self.player.stop()
            self.log("Stop requested: attempting to stop playback...")
        # stop MJT script runner if running
        try:
            if getattr(self, 'mjt_runner', None) and getattr(self.mjt_runner, 'running', False):
                self.mjt_runner.stop()
                self.log('Requested stop of MJT script')
        except Exception:
            pass
        # convert events into actions (simple conversion)
        # each event becomes an action with small delay
        for ev in self.recorder.events:
            if ev['type'] == 'move':
                continue
            if ev['type'] == 'click':
                if ev.get('pressed') == False:
                    self.actions.append({'action': 'click', 'pos': ev['pos']})
            if ev['type'] == 'key':
                if ev.get('pressed'):
                    self.actions.append({'action': 'key', 'key': ev['key']})
        self.signals.update_actions.emit()

    def on_play(self):
        if self._playing:
            QMessageBox.information(self, "Already playing", "Playback is already running")
            return
        # ask for repetitions and delay between repeats
        reps, ok = QInputDialog.getInt(self, "Repetitions", "How many times to repeat?", 1, 1, 10000, 1)
        if not ok:
            return
        delay_between, ok2 = QInputDialog.getDouble(self, "Delay between repetitions", "Seconds:", 0.5, 0, 3600, 2)
        if not ok2:
            delay_between = 0.5

        # prepare a simple representation of actions for playback
        def play_loop():
            self._playing = True
            self._stop_playback = False
            try:
                for r in range(reps):
                    if self._stop_playback:
                        break
                    events = []
                    t = 0.0
                    for a in self.actions:
                        if a.get('action') == 'delay':
                            t += float(a.get('seconds', 0.1))
                        elif a.get('action') == 'move_click':
                            events.append({'t': t, 'type': 'move', 'pos': tuple(a['pos'])})
                            events.append({'t': t + 0.01, 'type': 'click', 'pos': tuple(a['pos']), 'pressed': False})
                        elif a.get('action') == 'color_click':
                            # sample pixel, compare with tolerance
                            x, y = a.get('pos')
                            try:
                                px = pyautogui.screenshot().getpixel((int(x), int(y)))
                            except Exception:
                                px = (0, 0, 0)
                            color = tuple(a.get('color', (0, 0, 0)))
                            tol = a.get('tolerance', 30)
                            if color_matches(px, color, tol):
                                events.append({'t': t, 'type': 'move', 'pos': (int(x), int(y))})
                                events.append({'t': t + 0.01, 'type': 'click', 'pos': (int(x), int(y)), 'pressed': False})
                            else:
                                self.log(f"Color not matched at {(x,y)} (sample={px} target={color} tol={tol})")
                        elif a.get('action') == 'image_click':
                            # image clicks performed after event playback
                            pass
                    # play low-level events
                    self.player.play_events(events)
                    # wait for player to finish
                    while self.player._running and not self._stop_playback:
                        time.sleep(0.05)
                    # perform image clicks after events
                    for a in self.actions:
                        if a.get('action') == 'image_click':
                            coords = find_image_on_screen(a.get('image_path'), threshold=a.get('threshold', 0.8))
                            if coords:
                                self.log(f"Found image, clicking {coords}")
                                pyautogui.moveTo(int(coords[0]), int(coords[1]))
                                pyautogui.click()
                            else:
                                self.log("Image not found on screen")
                    if r < reps - 1 and not self._stop_playback:
                        time.sleep(float(delay_between))
            finally:
                self._playing = False
                self._stop_playback = False
                self.log("Playback finished or stopped")

        self._play_thread = threading.Thread(target=play_loop, daemon=True)
        self._play_thread.start()

    def refresh_actions(self):
        self.list_actions.clear()
        for a in self.actions:
            self.list_actions.addItem(json.dumps(a))

    def on_select_action(self):
        i = self.list_actions.currentRow()
        if i < 0 or i >= len(self.actions):
            self.editor.clear()
            return
        a = self.actions[i]
        try:
            self.editor.setPlainText(json.dumps(a, indent=2))
        except Exception:
            self.editor.setPlainText(str(a))

    # ---------- MJTNet script runner ----------
    def run_mjt_script(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open MJT Script", str(APP_DIR), "All Files (*);;Text Files (*.txt *.mjt)")
        if not fn:
            return
        with open(fn, 'r', encoding='utf-8', errors='ignore') as f:
            script = f.read()
        self.run_script_text(script, label=fn)

    def run_script_text(self, script_text: str, label: str = '<text>'):
        try:
            if getattr(self, 'mjt_runner', None) and getattr(self.mjt_runner, 'running', False):
                QMessageBox.information(self, "Runner running", "An MJT script is already running.")
                return
        except Exception:
            pass
        from mjt_runner import MJTScriptRunner
        self.mjt_runner = MJTScriptRunner(self.signals)
        self.mjt_thread = threading.Thread(target=self.mjt_runner.run, args=(script_text,), daemon=True)
        self.mjt_thread.start()
        self.log(f"Started MJT script: {label}")

    def stop_script(self):
        try:
            if getattr(self, 'mjt_runner', None) and getattr(self.mjt_runner, 'running', False):
                self.mjt_runner.stop()
                self.log('Requested MJT script stop')
        except Exception:
            pass


    def add_delay_action(self):
        secs, ok = QInputDialog.getDouble(self, "Delay seconds", "Seconds:", 0.5, 0, 3600, 2)
        if not ok:
            return
        self.actions.append({'action': 'delay', 'seconds': float(secs)})
        self.refresh_actions()

    def add_move_click_action(self):
        self.log("Move cursor to desired location and press Enter to capture position")
        QMessageBox.information(self, "Capture", "Move your mouse to desired location and press OK to capture current cursor position.")
        x, y = pyautogui.position()
        self.actions.append({'action': 'move_click', 'pos': (int(x), int(y))})
        self.refresh_actions()

    def add_color_action(self):
        # Open the color picker tool and add the selected color when the user picks it
        picker = ColorPicker(self)
        picker.color_picked.connect(self.add_color_action_at)
        picker.show()

    def open_color_picker(self):
        picker = ColorPicker(self)
        picker.color_picked.connect(self.add_color_action_at)
        picker.show()

    def open_script_editor(self):
        dlg = QWidget()
        dlg.setWindowTitle('MJT Script Editor')
        dlg.setWindowFlags(dlg.windowFlags() | Qt.Tool)
        dlg.resize(700, 500)
        layout = QVBoxLayout(dlg)
        editor = QTextEdit()
        layout.addWidget(editor)
        btn_row = QHBoxLayout()
        btn_load = QPushButton('Load...')
        btn_save = QPushButton('Save...')
        btn_run = QPushButton('Run')
        btn_stop = QPushButton('Stop')
        btn_step = QPushButton('Step')
        btn_resume = QPushButton('Resume')
        btn_insert = QPushButton('Insert to Actions')
        btn_row.addWidget(btn_load)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_run)
        btn_row.addWidget(btn_stop)
        btn_row.addWidget(btn_step)
        btn_toggle_bp = QPushButton('Toggle Breakpoint')
        btn_show_bps = QPushButton('Breakpoints')
        btn_row.addWidget(btn_toggle_bp)
        btn_row.addWidget(btn_show_bps)
        btn_row.addWidget(btn_resume)
        btn_row.addWidget(btn_insert)
        layout.addLayout(btn_row)

        def load_file():
            fn, _ = QFileDialog.getOpenFileName(self, 'Open script', str(APP_DIR), 'MJT Files (*.mjt *.txt);;All Files (*)')
            if not fn:
                return
            with open(fn, 'r', encoding='utf-8', errors='ignore') as f:
                editor.setPlainText(f.read())

        def save_file():
            fn, _ = QFileDialog.getSaveFileName(self, 'Save script', str(APP_DIR / 'script.mjt'), 'MJT Files (*.mjt *.txt);;All Files (*)')
            if not fn:
                return
            with open(fn, 'w', encoding='utf-8') as f:
                f.write(editor.toPlainText())

        # debugger
        from mjt_runner import MJTDebugger
        dbg = MJTDebugger(self.signals.log.emit)

        # variable table
        var_table = QTableWidget()
        var_table.setColumnCount(2)
        var_table.setHorizontalHeaderLabels(['Variable', 'Value'])
        layout.addWidget(var_table)

        def refresh_vars():
            state = dbg.get_state()
            vars = state.get('variables', {})
            var_table.setRowCount(len(vars))
            for i, (k, v) in enumerate(sorted(vars.items())):
                var_table.setItem(i, 0, QTableWidgetItem(str(k)))
                var_table.setItem(i, 1, QTableWidgetItem(str(v)))

        def run_text():
            txt = editor.toPlainText()
            dbg.load(txt)
            dbg.run()
            # poll state while running
            def poll():
                while dbg.get_state().get('running'):
                    refresh_vars()
                    time.sleep(0.1)
                refresh_vars()
            threading.Thread(target=poll, daemon=True).start()

        def stop_text():
            dbg.stop()

        def step_text():
            txt = editor.toPlainText()
            if dbg.lines == []:
                dbg.load(txt)
            ok = dbg.step()
            refresh_vars()
            if not ok:
                QMessageBox.information(self, 'Debugger', 'No more lines to step or debugger stopped')

        def toggle_breakpoint_ui():
            # determine current cursor line in editor and map to debugger line index
            cursor = editor.textCursor()
            block = cursor.blockNumber()  # 0-based in full editor
            full_lines = editor.toPlainText().splitlines()
            if block >= len(full_lines):
                QMessageBox.warning(self, 'Breakpoint', 'No line under cursor')
                return
            # count non-empty, non-comment lines up to block
            idx = -1
            for i in range(0, block+1):
                l = full_lines[i]
                if not l.strip():
                    continue
                up = l.lstrip()
                if up.upper().startswith('REM') or l.strip().startswith(';'):
                    continue
                idx += 1
            if idx < 0:
                QMessageBox.warning(self, 'Breakpoint', 'No executable statement at this line')
                return
            dbg.toggle_breakpoint(idx)
            QMessageBox.information(self, 'Breakpoint', f'Toggled breakpoint at logical line {idx+1}')

        def show_breakpoints_ui():
            bps = dbg.list_breakpoints()
            if not bps:
                QMessageBox.information(self, 'Breakpoints', 'No breakpoints set')
            else:
                QMessageBox.information(self, 'Breakpoints', 'Breakpoints at lines: ' + ','.join(str(x) for x in bps))

        def resume_text():
            txt = editor.toPlainText()
            if dbg.lines == []:
                dbg.load(txt)
            dbg.resume()
            def poll2():
                while dbg.get_state().get('running'):
                    refresh_vars()
                    time.sleep(0.1)
                refresh_vars()
            threading.Thread(target=poll2, daemon=True).start()

        def insert_actions():
            txt = editor.toPlainText()
            # append as a comment action
            self.actions.append({'action': 'mjt_script', 'script': txt})
            self.refresh_actions()

        btn_load.clicked.connect(load_file)
        btn_save.clicked.connect(save_file)
        btn_run.clicked.connect(run_text)
        btn_stop.clicked.connect(stop_text)
        btn_step.clicked.connect(step_text)
        btn_toggle_bp.clicked.connect(toggle_breakpoint_ui)
        btn_show_bps.clicked.connect(show_breakpoints_ui)
        btn_resume.clicked.connect(resume_text)
        btn_insert.clicked.connect(insert_actions)

        dlg.show()

    def open_event_manager(self):
        dlg = QWidget()
        dlg.setWindowTitle('Event Manager')
        dlg.setWindowFlags(dlg.windowFlags() | Qt.Tool)
        dlg.resize(600, 400)
        layout = QVBoxLayout(dlg)
        listw = QListWidget()
        layout.addWidget(listw)
        btn_row = QHBoxLayout()
        btn_add = QPushButton('Add Event')
        btn_remove = QPushButton('Remove')
        btn_start = QPushButton('Start Monitors')
        btn_stop = QPushButton('Stop Monitors')
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_remove)
        btn_row.addWidget(btn_start)
        btn_row.addWidget(btn_stop)
        layout.addLayout(btn_row)

        monitors = []

        def refresh_list():
            listw.clear()
            for m in monitors:
                listw.addItem(json.dumps(m['spec']))

        def add_event():
            # ask type
            etype, ok = QInputDialog.getItem(self, 'Event Type', 'Select event type', ['PIXEL_COLOR','FILE_EXISTS','KEY_DOWN','CUSTOM'], 0, False)
            if not ok:
                return
            if etype == 'PIXEL_COLOR':
                xy, ok = QInputDialog.getText(self, 'Coord', 'Enter X,Y:')
                if not ok:
                    return
                color, ok2 = QInputDialog.getText(self, 'Color', 'Enter color hex or decimal:')
                if not ok2:
                    return
                sub, ok3 = QInputDialog.getText(self, 'Subroutine', 'Subroutine name to call:')
                if not ok3:
                    return
                try:
                    x,y = [int(p.strip()) for p in xy.split(',')]
                except Exception:
                    QMessageBox.warning(self, 'Invalid', 'Invalid coordinates')
                    return
                spec = {'type':'PIXEL_COLOR','coord':(x,y),'color':color,'sub':sub}
            elif etype == 'FILE_EXISTS':
                fn, ok = QFileDialog.getOpenFileName(self, 'Select file to watch')
                if not ok or not fn:
                    return
                sub, ok2 = QInputDialog.getText(self, 'Subroutine', 'Subroutine name to call:')
                if not ok2:
                    return
                spec = {'type':'FILE_EXISTS','path':fn,'sub':sub}
            elif etype == 'KEY_DOWN':
                key, ok = QInputDialog.getText(self, 'Key', 'Key to watch (single char or VK code):')
                if not ok:
                    return
                sub, ok2 = QInputDialog.getText(self, 'Subroutine', 'Subroutine name to call:')
                if not ok2:
                    return
                spec = {'type':'KEY_DOWN','key':key,'sub':sub}
            else:
                var, ok = QInputDialog.getText(self, 'Var', 'Variable name to watch (CUSTOM trigger):')
                if not ok:
                    return
                sub, ok2 = QInputDialog.getText(self, 'Subroutine', 'Subroutine name to call:')
                if not ok2:
                    return
                spec = {'type':'CUSTOM','var':var,'sub':sub}
            monitors.append({'spec':spec, 'running':False})
            refresh_list()

        def remove_event():
            i = listw.currentRow()
            if i < 0:
                return
            monitors.pop(i)
            refresh_list()

        def start_monitors():
            # build an MJT script with SRT/END blocks and OnEvent lines
            script_lines = []
            for m in monitors:
                s = m['spec']
                sub = s.get('sub','OnEvt')
                if s['type']=='PIXEL_COLOR':
                    x,y = s['coord']
                    color = s['color']
                    script_lines.append(f"SRT>{sub}")
                    script_lines.append(f" Message>{sub} triggered")
                    script_lines.append(f" End>{sub}")
                    script_lines.append(f"OnEvent>PIXEL_COLOR,{x}:{y},{color},{sub}")
                elif s['type']=='FILE_EXISTS':
                    script_lines.append(f"SRT>{sub}")
                    script_lines.append(f" Message>{sub} triggered")
                    script_lines.append(f" End>{sub}")
                    script_lines.append(f"OnEvent>FILE_EXISTS,{s['path']},0,{sub}")
                elif s['type']=='KEY_DOWN':
                    script_lines.append(f"SRT>{sub}")
                    script_lines.append(f" Message>{sub} triggered")
                    script_lines.append(f" End>{sub}")
                    script_lines.append(f"OnEvent>KEY_DOWN,{s['key']},0,{sub}")
                elif s['type']=='CUSTOM':
                    script_lines.append(f"SRT>{sub}")
                    script_lines.append(f" Message>{sub} triggered")
                    script_lines.append(f" End>{sub}")
                    script_lines.append(f"OnEvent>CUSTOM,{s['var']},0,{sub}")
            script = '\n'.join(script_lines)
            self.run_script_text(script, label='event_manager')
            self.log('Started event manager script')

        def stop_monitors():
            self.stop_script()
            self.log('Stopped event manager script')

        btn_add.clicked.connect(add_event)
        btn_remove.clicked.connect(remove_event)
        btn_start.clicked.connect(start_monitors)
        btn_stop.clicked.connect(stop_monitors)

        dlg.show()
    def add_color_action_at(self, x, y, rgb):
        try:
            # ask tolerance (0-255)
            tol, ok = QInputDialog.getInt(self, "Tolerance", "Color tolerance (0-255):", 30, 0, 255, 1)
            if not ok:
                tol = 30
            self.actions.append({'action': 'color_click', 'pos': (int(x), int(y)), 'color': tuple(rgb), 'tolerance': int(tol)})
            self.refresh_actions()
            self.log(f"Captured color {rgb} at {(x,y)} with tolerance {tol}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to add color action: {e}")
            self.signals.log.emit(f"Add color error: {e}")

    def add_image_action(self):
        QMessageBox.information(self, "Capture region", "You will be prompted to select an image file to use as a template to match on screen (take a screenshot region with PrintScreen or use an external tool).")
        fn, _ = QFileDialog.getOpenFileName(self, "Select template image")
        if not fn:
            return
        # copy image into macros dir
        src = Path(fn)
        dest = MACROS_DIR / (src.name)
        if not dest.exists():
            import shutil
            shutil.copy(src, dest)
        thresh, ok = QInputDialog.getDouble(self, "Threshold", "Match threshold (0.5-0.99):", 0.8, 0.5, 0.99, 2)
        if not ok:
            thresh = 0.8
        self.actions.append({'action': 'image_click', 'image_path': str(dest), 'threshold': float(thresh)})
        self.refresh_actions()

    def save_macro(self):
        name, ok = QInputDialog.getText(self, "Macro name", "Name for macro:")
        if not ok or not name:
            return
        path = MACROS_DIR / f"{name}.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.actions, f, indent=2)
        self.log(f"Saved macro to {path}")

    def load_macro(self):
        files = [str(p) for p in MACROS_DIR.glob('*.json')]
        if not files:
            QMessageBox.information(self, "No macros", "No saved macros found in macros/ directory")
            return
        fn, ok = QInputDialog.getItem(self, "Load macro", "Select macro file:", files, 0, False)
        if not ok or not fn:
            return
        with open(fn, 'r', encoding='utf-8') as f:
            self.actions = json.load(f)
        self.refresh_actions()
        self.log(f"Loaded macro {fn}")

    def export_json(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Export JSON", str(APP_DIR / "macro_export.json"), "JSON Files (*.json)")
        if not fn:
            return
        with open(fn, 'w', encoding='utf-8') as f:
            json.dump(self.actions, f, indent=2)
        self.log(f"Exported macro to {fn}")

    def update_action(self):
        i = self.list_actions.currentRow()
        if i < 0 or i >= len(self.actions):
            QMessageBox.warning(self, "No selection", "No action selected to update.")
            return
        txt = self.editor.toPlainText()
        try:
            a = json.loads(txt)
        except Exception as e:
            QMessageBox.warning(self, "Invalid JSON", f"Failed to parse JSON: {e}")
            return
        self.actions[i] = a
        self.refresh_actions()
        self.list_actions.setCurrentRow(i)

    def delete_action(self):
        i = self.list_actions.currentRow()
        if i < 0 or i >= len(self.actions):
            return
        try:
            self.actions.pop(i)
        except Exception as e:
            QMessageBox.warning(self, "Delete failed", f"Failed to delete action: {e}")
            self.signals.log.emit(f"Delete error: {e}")
            return
        self.refresh_actions()
        self.editor.clear()
        if self.actions:
            sel = min(i, len(self.actions) - 1)
            self.list_actions.setCurrentRow(sel)
        else:
            self.list_actions.clearSelection()
        # stop mjt runner if running
        try:
            if getattr(self, 'mjt_runner', None) and getattr(self.mjt_runner, 'running', False):
                self.mjt_runner.stop()
                self.log('Stopped running MJT script due to action deletion')
        except Exception:
            pass

    def move_action_up(self):
        i = self.list_actions.currentRow()
        if i <= 0:
            return
        self.actions[i - 1], self.actions[i] = self.actions[i], self.actions[i - 1]
        self.refresh_actions()
        self.list_actions.setCurrentRow(i - 1)

    def move_action_down(self):
        i = self.list_actions.currentRow()
        if i < 0 or i >= len(self.actions) - 1:
            return
        self.actions[i + 1], self.actions[i] = self.actions[i], self.actions[i + 1]
        self.refresh_actions()
        self.list_actions.setCurrentRow(i + 1)


def main():
    app = QApplication(sys.argv)
    w = MacroApp()
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
