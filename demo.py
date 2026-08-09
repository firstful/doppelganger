"""desktopx usage demo: enumerate windows, locate text by OCR, click it, verify."""
import time

from desktopx import Desktop, ocr_text
from desktopx.capture import screenshot
from desktopx.ocr import find_text, find_click


def main():
    d = Desktop()  # picks x11 / wayland / windows / macos automatically
    print(f"backend: {d.name}")

    print("\nvisible windows:")
    for w in d.list_windows():
        g = w.geometry()
        if g.get("width", 0) > 300 and g.get("height", 0) > 200:
            print(f"  {w.title[:60]!r}  {g['width']}x{g['height']} @ {g['x']},{g['y']}")

    target = input("\nOCR text to click (Enter to skip): ").strip()
    if not target:
        return

    p, _ = screenshot()
    print(f"located {target!r} at {find_text(target, p)}")
    loc = find_click(target)
    print("clicked at", loc)
    time.sleep(3)

    p2, _ = screenshot()
    print("after:", " ".join(ocr_text(p2).split()[:18]))


if __name__ == "__main__":
    main()