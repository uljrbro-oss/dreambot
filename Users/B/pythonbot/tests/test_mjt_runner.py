import time
import pytest
from mjt_runner import MJTInterpreter, RunnerAPI, EvalError


class DummyAPI(RunnerAPI):
    def __init__(self):
        self._pixels = {}
        self.clicked = []
        self.moved = []

    def set_pixel(self, x, y, rgb):
        self._pixels[(int(x), int(y))] = rgb

    def click(self, x=None, y=None):
        self.clicked.append((x, y))

    def move(self, x, y):
        self.moved.append((x, y))

    def screenshot_getpixel(self, x, y):
        return self._pixels.get((int(x), int(y)), (0, 0, 0))


def test_let_and_eval():
    it = MJTInterpreter()
    it.run('Let>k=1\nLet>k=k+2\nMessage>done')
    assert it.variables['k'] == 3


def test_lclick_and_mousemove():
    api = DummyAPI()
    it = MJTInterpreter(log_fn=print, runner_api=api)
    it.run('MouseMove>10,20\nLClick')
    assert api.moved == [(10, 20)]
    assert len(api.clicked) == 1


def test_getpixelcolor_and_wpc_timeout():
    api = DummyAPI()
    api.set_pixel(20, 30, (77, 169, 49))  # some color
    it = MJTInterpreter(log_fn=print, runner_api=api)
    # GPC should read the pixel
    it.run('GPC>20,30,PC')
    assert 'PC' in it.variables

    # WPC with a timeout that passes (target is present)
    script = 'WPC>#4DA931,20,30,0.5'
    it.run(script)
    assert it.variables.get('WPC_RESULT', 0) == 1

    # WPC with a different pixel should timeout and set result 0
    api.set_pixel(40, 50, (10, 10, 10))
    it.run('WPC>#FFFFFF,40,50,0.2')
    assert it.variables.get('WPC_RESULT', 0) == 0


def test_repeat_until_loop():
    it = MJTInterpreter()
    script = 'Let>k=0\nRepeat>k\n Let>k=k+1\n Until>k,3\n'
    it.run(script)
    assert it.variables['k'] == 3
