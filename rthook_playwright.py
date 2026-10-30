# -*- coding: utf-8 -*-
"""PyInstaller runtime hook for Playwright on macOS.

Ensures PLAYWRIGHT_BROWSERS_PATH points to the bundled ms-playwright
directory inside Contents/Resources when running as a packaged macOS .app.
"""

import os
import sys
from pathlib import Path


def _init_playwright_browsers_path():
    if not (getattr(sys, "frozen", False) and sys.platform == "darwin"):
        return

    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return

    # Check Contents/Resources/ms-playwright relative to executable
    try:
        exe_path = Path(sys.executable).resolve()
        # exe is at <App>.app/Contents/MacOS/<exe>
        cand = exe_path.parent.parent / "Resources" / "ms-playwright"
        if cand.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cand)
            return
    except Exception:
        pass

    # Check relative to _MEIPASS if present
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        try:
            m_path = Path(meipass).resolve()
            for cand in [
                m_path.parent / "Resources" / "ms-playwright",
                m_path / "Resources" / "ms-playwright",
                m_path / "ms-playwright",
            ]:
                if cand.is_dir():
                    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cand)
                    return
        except Exception:
            pass


_init_playwright_browsers_path()
