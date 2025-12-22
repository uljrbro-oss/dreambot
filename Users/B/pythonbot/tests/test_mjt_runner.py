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


def test_findimage_and_waitscreenimage(tmp_path):
    # create a small template and a screenshot containing it
    import numpy as _np
    import cv2
    tpl = _np.zeros((10, 10, 3), dtype=_np.uint8)
    tpl[:] = (0, 0, 255)  # red box in BGR
    tpl_path = tmp_path / 'tpl.png'
    cv2.imwrite(str(tpl_path), tpl)

    # create a larger screenshot with the template at position (50,60)
    screen = _np.zeros((200, 300, 3), dtype=_np.uint8)
    # put red box in screen at y=60..69, x=50..59 (BGR)
    screen[60:70, 50:60] = (0, 0, 255)

    class ImageAPI(DummyAPI):
        def screenshot(self):
            # return a PIL Image-like object; we can return numpy array and RunnerAPI handles it
            return screen[:, :, ::-1]  # convert BGR to RGB
        def screenshot_getpixel(self, x, y):
            # return pixel from the screen
            rgb = tuple(int(v) for v in screen[y, x, ::-1])
            return rgb

    api = ImageAPI()
    it = MJTInterpreter(log_fn=print, runner_api=api)
    # FINDIMAGEPOS>tpl,varx,vary
    it.run(f'FINDIMAGEPOS>{tpl_path},RX,RY')
    assert it.variables['RX'] == 55 and it.variables['RY'] == 65

    # WAITSCREENIMAGE: should set variable
    it.run(f'WSI>{tpl_path},0.2,WSI')
    assert it.variables.get('WSI', 0) == 1


def test_repeat_until_loop():
    it = MJTInterpreter()
    script = 'Let>k=0\nRepeat>k\n Let>k=k+1\n Until>k,3\n'
    it.run(script)
    assert it.variables['k'] == 3


def test_if_else_and_goto():
    it = MJTInterpreter()
    # simple IF true
    script = 'Let>k=0\nIf>k=0\n Let>r=1\nElse\n Let>r=2\nEndIf\n'
    it.run(script)
    assert it.variables['r'] == 1
    # simple IF false
    script2 = 'Let>k=1\nIf>k=0\n Let>r=1\nElse\n Let>r=2\nEndIf\n'
    it.run(script2)
    assert it.variables['r'] == 2

    # GOTO / LABEL loop example
    script3 = 'Let>k=0\nLabel>start\n Let>k=k+1\n If>k=3\n  Goto>end\n EndIf\n Goto>start\nLabel>end\n'
    it.run(script3)
    assert it.variables['k'] == 3
