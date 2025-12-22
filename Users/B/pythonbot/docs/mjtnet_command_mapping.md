# MJTNet Command Mapping & Prioritization

Purpose: Catalog every MJTNet command (by group) and map it to implementation tasks, dependencies, and priorities so we can implement full MJTNet support safely and incrementally.

---

## Summary
We will implement the full MJTNet command reference in phases. Each command group is mapped to required app capabilities (e.g., mouse: pyautogui; image: OpenCV; windows: pywinauto or pywin32; http/ftp: requests, ftplib). Commands that pose higher security or optional external dependencies are marked as optional and will be gated behind config/opt-in.

## High-level groups (initial mapping)
- Mouse Commands (LClick, LDown, LUp, MouseMove, MouseMoveRel, MouseOver, RClick, etc.)
  - Implementation: pyautogui
  - Priority: High

- Keyboard Commands (Press, HoldKey, WaitKeyDown, SendText)
  - Implementation: pyautogui / pynput
  - Priority: High

- Image Recognition (FindImagePos, WaitScreenImage, GetPixelColor, WaitPixelColor)
  - Implementation: OpenCV, numpy
  - Priority: High

- Control Flow (Repeat/Until, While/EndWhile, Goto/Label, If/Else/EndIf, Exit)
  - Implementation: interpreter control structures
  - Priority: High

- Variables & Expressions (Let, complex expressions, environment variables)
  - Implementation: interpreter variable storage + safe evaluator (AST-based)
  - Priority: High

- Events & Scheduler (OnEvent, custom triggers, PIXEL_COLOR)
  - Implementation: background monitors / event handlers, UI to manage
  - Priority: High

- Window Functions (IfWindowOpen, SetFocus, WindowObjects)
  - Implementation: pywinauto / pywin32 (optional dependency)
  - Priority: Medium

- File/IO (File handling, GetFileList, FileExists, Delete/Copy/Move)
  - Implementation: Python stdlib; careful sandboxing
  - Priority: Medium

- Network (FTP/HTTP, Email) & Console app functions
  - Implementation: requests / ftplib / smtplib; opt-in
  - Priority: Low/Optional

- Dialogs & Messages (Message, MessageModal, dialogs)
  - Implementation: Qt dialogs for modal; fallback to log
  - Priority: Medium

- Misc (Registry, DDE, Excel integration)
  - Implementation: pywin32, optional; riskier or platform-specific
  - Priority: Low/Optional

---

## Implementation notes & safety
- All commands that run system or network operations will require explicit enablement in the app settings.
- Expression evaluation will use a restricted AST evaluator (no import, no attribute access).
- Running scripts will always be stoppable via the Stop button, and long waits are split into short sleeps to allow responsiveness.
- Image commands will expose threshold/tolerance, and allow scanning regions.

---

## Roadmap / Prioritized tasks (short-term backlog)
1. Core interpreter & variables (LET, expressions, safe evaluator) — HIGH
2. Control flow constructs (LABEL/GOTO, REPEAT/UNTIL, IF/ELSE) — HIGH
3. Mouse & keyboard commands (LClick, MouseMove, Press, WaitKeyDown) — HIGH
4. Image & pixel commands (GetPixelColor, WaitPixelColor, FindImagePos) — HIGH
5. Events & OnEvent (PIXEL_COLOR, KEY_DOWN) & monitor integration — HIGH
6. UI: MJT script editor + run/step/stop + variable watch — MEDIUM
7. Window functions (SetFocus, IfWindowOpen) — MEDIUM
8. File & Clipboard & Dialogs — MEDIUM
9. Network (HTTP/FTP/Email) — LOW/Optional
10. Advanced Windows/Excel/DDE/Registry — OPTIONAL

---

## Next steps (immediate)
- Start implementing "Core interpreter & variables" on branch `feature/mjtnet-full` (create PR when ready).
- Add unit tests for safe evaluator and small command-run scenarios.
- Add example MJT scripts under `examples/mjt/` for test coverage.

---

If you'd like, I can now:
- Add the initial `examples/mjt/` folder with a few example scripts (monitor color, click loop, image wait), and commit them to the branch.
- Begin implementing the interpreter core (parser + AST) and provide a PR for review.

Tell me which of these to do next, or approve both and I’ll proceed to implement the interpreter core right away.