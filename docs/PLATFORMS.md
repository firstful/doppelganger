# Platform Support Matrix

`desktopx` auto-detects the best backend at import time
(`desktopx.platform.detect_backend`) and exposes one uniform driver API.

## Backends

| Feature       | X11 (xdotool)      | Wayland (ydotool)  | Windows (pyautogui+win32) | macOS (pyautogui) |
|---------------|--------------------|--------------------|---------------------------|-------------------|
| Detection     | `xdpyinfo` OK      | `WAYLAND_DISPLAY`  | `platform == Windows`     | `platform == Darwin` |
| Windows list  | `xdotool search`   | XWayland fallback  | `win32gui.EnumWindows`    | best effort / [] |
| Activate      | `windowactivate`   | no-op              | `SetForegroundWindow`     | inherited Win    |
| Geometry      | `getwindowgeometry`| 0s                 | `GetWindowRect`           | inherited Win    |
| Move/resize   | `windowmove/size`  | no-op              | `SetWindowPos`            | inherited Win    |
| Screenshot    | ImageMagick `import -window root|WID` | `spectacle -f -b -n` | `pyautogui.screenshot()` | inherited Win |
| Mouse move    | `mousemove`        | `mousemove -a`     | `moveTo(duration)`        | inherited Win    |
| Click         | `xdotool click 1`  | `ydotool click 0xC0`| `click()`                | inherited Win    |
| Keyboard      | `type --delay`     | `ydotool type`     | `typewrite`               | inherited Win    |
| Scroll        | wheel click repeat | wheel `-w`         | `scroll()`                | inherited Win    |
| Human pathing | bezier + jitter    | best effort        | pyautogui duration        | inherited Win    |

## Detection rules (Linux)

1. If an X server answers `xdpyinfo` on `$DISPLAY` (or `:98`), use **x11**.
2. Else if `WAYLAND_DISPLAY` is set, use **wayland**.
3. Else fall back to **x11**.

## Notes / gotchas

- **Wayland live desktop is not safe for automation.** XTEST clicks are
  ignored by KWin and `ydotool` pointer moves did not register on the real
  desktop. Keep automation on an isolated `Xvfb` display (e.g. `:98`).
- `X11Driver.screenshot(win_id)` captures a single window and returns its
  geometry; `screenshot(screen=True)` captures the root window.
- On Wayland, `list_windows()` delegates to the XWayland `X11Driver` when an
  X server is present, else returns `[]`.
- Windows/macOS drivers degrade gracefully to empty window lists when
  optional deps (`pywin32` / `pyautogui`) are missing.

## Operating modes for `desktop.py`

- `INPUT_MODE=ydotool` (default) — kernel uinput path (Wayland).
- `INPUT_MODE=xdotool` — XTEST path; required on `Xvfb :98`.
