# -*- coding: utf-8 -*-
"""Runtime environment setup for TikTok Video Performance.

Configures environment variables such as PLAYWRIGHT_BROWSERS_PATH when running
in a packaged macOS .app bundle without affecting normal development or other platforms.
"""

import os
import sys
from pathlib import Path
from typing import Optional


def get_bundled_playwright_browsers_path() -> Optional[Path]:
    """Find the bundled ms-playwright directory if running in a frozen macOS app.

    Returns:
        Path to Contents/Resources/ms-playwright if it exists, otherwise None.
    """
    if not getattr(sys, "frozen", False):
        return None

    if sys.platform != "darwin":
        return None

    candidates: list[Path] = []

    # Standard macOS .app layout:
    # <App>.app/Contents/MacOS/<executable> -> Contents/Resources/ms-playwright
    try:
        exe_path = Path(sys.executable).resolve()
        candidates.append(exe_path.parent.parent / "Resources" / "ms-playwright")
    except Exception:
        pass

    # PyInstaller _MEIPASS layout
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        try:
            m_path = Path(meipass).resolve()
            candidates.extend([
                m_path.parent / "Resources" / "ms-playwright",
                m_path / "Resources" / "ms-playwright",
                m_path / "ms-playwright",
            ])
        except Exception:
            pass

    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate
        except Exception:
            continue

    return None


def setup_playwright_environment() -> Optional[str]:
    """Configure PLAYWRIGHT_BROWSERS_PATH for the bundled browser if present.

    Only sets PLAYWRIGHT_BROWSERS_PATH when:
    1. Running frozen (PyInstaller) on macOS.
    2. PLAYWRIGHT_BROWSERS_PATH is not already explicitly set.
    3. The bundled ms-playwright directory exists.

    Returns:
        The configured path string, or None if unchanged.
    """
    if "PLAYWRIGHT_BROWSERS_PATH" in os.environ:
        return os.environ["PLAYWRIGHT_BROWSERS_PATH"]

    bundled_path = get_bundled_playwright_browsers_path()
    if bundled_path is not None:
        path_str = str(bundled_path)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = path_str
        return path_str

    return None


# Execute setup upon module import
setup_playwright_environment()
