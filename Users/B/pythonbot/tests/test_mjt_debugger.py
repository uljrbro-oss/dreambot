import time
from mjt_runner import MJTDebugger


def test_breakpoint_pause_and_resume():
    dbg = MJTDebugger(print)
    script = """
    Let>k=0
    Let>k=k+1
    Let>k=k+2
    """
    dbg.load(script)
    # set breakpoint on first executable line (index 0)
    dbg.toggle_breakpoint(0)
    # run - should pause at first breakpoint without executing
    dbg.run()
    time.sleep(0.1)
    state = dbg.get_state()
    assert state['pc'] == 0
    assert state['running'] == False
    # resume
    dbg.resume()
    time.sleep(0.2)
    state2 = dbg.get_state()
    # script should have executed to completion
    assert state2['variables'].get('k', 0) == 3


def test_debugger_goto_and_if():
    dbg = MJTDebugger(print)
    script = """
    Let>k=0
    Label>start
    Let>k=k+1
    If>k=3
      Goto>end
    EndIf
    Goto>start
    Label>end
    """
    dbg.load(script)
    # step through until completion
    while dbg.step():
        pass
    assert dbg.variables.get('k', 0) == 3
