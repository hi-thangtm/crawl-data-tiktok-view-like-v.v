import json
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


APP_NAME = "TikTok Video Performance"

SESSION_READY = "READY"
SESSION_MISSING = "MISSING"
SESSION_INVALID = "INVALID"
SESSION_EXPIRED = "EXPIRED"
SESSION_UNKNOWN = "UNKNOWN"

AUTH_COOKIE_NAMES = {
    "sessionid",
    "sessionid_ss",
    "sid_guard",
    "sid_tt",
    "uid_tt",
    "uid_tt_ss",
}


def get_app_data_dir() -> Path:
    """Return a writable per-user data directory."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path.home() / "AppData" / "Local"
    else:
        base = Path.home() / ".local" / "share"

    return base / APP_NAME


APP_DATA_DIR = get_app_data_dir()
SESSION_STATE_FILE = APP_DATA_DIR / "tiktok_state.json"

# Development-only legacy location. Do not include this file in the final app.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_SESSION_FILE = PROJECT_ROOT / "data" / "tiktok_state.json"


def ensure_app_data_dir() -> Path:
    APP_DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    return APP_DATA_DIR


def migrate_legacy_session() -> bool:
    """Copy the old development session once on the developer machine."""
    ensure_app_data_dir()

    if SESSION_STATE_FILE.exists():
        return False

    if not LEGACY_SESSION_FILE.exists():
        return False

    try:
        shutil.copy2(
            LEGACY_SESSION_FILE,
            SESSION_STATE_FILE,
        )
        return True
    except Exception:
        return False


def _load_state() -> dict | None:
    migrate_legacy_session()

    try:
        if not SESSION_STATE_FILE.exists():
            return None

        if not SESSION_STATE_FILE.is_file():
            return None

        if SESSION_STATE_FILE.stat().st_size < 20:
            return None

        data = json.loads(
            SESSION_STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            return None

        return data

    except Exception:
        return None


def _is_tiktok_cookie(cookie: dict) -> bool:
    domain = str(
        cookie.get("domain")
        or ""
    ).lower()

    return (
        "tiktok.com" in domain
        or "tiktokv.com" in domain
    )


def _cookie_is_expired(cookie: dict) -> bool:
    expires = cookie.get("expires")

    # Playwright uses -1 / 0 for session cookies.
    if expires in (None, -1, 0, 0.0):
        return False

    try:
        return float(expires) <= time.time()
    except Exception:
        return False


def _has_active_auth_cookie(cookies) -> bool:
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue

        if not _is_tiktok_cookie(cookie):
            continue

        name = str(
            cookie.get("name")
            or ""
        ).lower()

        if name not in AUTH_COOKIE_NAMES:
            continue

        value = str(
            cookie.get("value")
            or ""
        ).strip()

        if not value:
            continue

        if _cookie_is_expired(cookie):
            continue

        return True

    return False


def inspect_session_local() -> tuple[str, str]:
    """
    Fast local check without opening a browser.

    READY here means the state file looks usable; the live check below is the
    stronger validation used by the GUI on startup.
    """
    migrate_legacy_session()

    if not SESSION_STATE_FILE.exists():
        return (
            SESSION_MISSING,
            "Chưa có TikTok Session trên máy này.",
        )

    try:
        raw = SESSION_STATE_FILE.read_text(
            encoding="utf-8"
        )
        state = json.loads(raw)
    except Exception:
        return (
            SESSION_INVALID,
            "File TikTok Session không hợp lệ.",
        )

    if not isinstance(state, dict):
        return (
            SESSION_INVALID,
            "File TikTok Session không đúng định dạng.",
        )

    cookies = state.get("cookies")

    if not isinstance(cookies, list):
        return (
            SESSION_INVALID,
            "TikTok Session không chứa dữ liệu cookie hợp lệ.",
        )

    if not _has_active_auth_cookie(cookies):
        return (
            SESSION_EXPIRED,
            "TikTok Session không còn cookie đăng nhập còn hiệu lực.",
        )

    return (
        SESSION_READY,
        "TikTok Session có dữ liệu đăng nhập hợp lệ.",
    )


def has_session() -> bool:
    status, _ = inspect_session_local()
    return status == SESSION_READY


def delete_session() -> bool:
    try:
        if SESSION_STATE_FILE.exists():
            SESSION_STATE_FILE.unlink()
        return True
    except Exception:
        return False


def _looks_like_login_url(url: str) -> bool:
    url = (url or "").lower()

    return (
        "/login" in url
        or "login?" in url
        or "/signup" in url
    )


def check_session_live(
    timeout_ms: int = 25000,
) -> tuple[str, str]:
    """
    Validate the saved session with a short hidden Chrome check.

    Network / TikTok availability failures return UNKNOWN rather than EXPIRED,
    so a temporary connection issue does not force the user to sign in again.
    """
    local_status, local_message = inspect_session_local()

    if local_status != SESSION_READY:
        return local_status, local_message

    browser = None
    context = None

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    channel="chrome",
                    headless=True,
                )
            except Exception:
                browser = p.chromium.launch(
                    headless=True,
                )

            context = browser.new_context(
                storage_state=str(
                    SESSION_STATE_FILE
                ),
                viewport={
                    "width": 1280,
                    "height": 800,
                },
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
            )

            page = context.new_page()

            # The settings route is expected to require an authenticated
            # session. If TikTok redirects it to login, the state has expired.
            page.goto(
                "https://www.tiktok.com/setting?lang=vi-VN",
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            final_url = page.url

            if _looks_like_login_url(final_url):
                return (
                    SESSION_EXPIRED,
                    "TikTok đã yêu cầu đăng nhập lại.",
                )

            current_cookies = context.cookies(
                "https://www.tiktok.com/"
            )

            if not _has_active_auth_cookie(
                current_cookies
            ):
                return (
                    SESSION_EXPIRED,
                    "TikTok Session không còn cookie đăng nhập hợp lệ.",
                )

            return (
                SESSION_READY,
                "TikTok Session đang hoạt động.",
            )

    except PlaywrightTimeoutError:
        return (
            SESSION_UNKNOWN,
            "Không thể xác minh TikTok Session lúc này do TikTok phản hồi chậm.",
        )

    except Exception as exc:
        return (
            SESSION_UNKNOWN,
            (
                "Không thể xác minh TikTok Session lúc này: "
                f"{type(exc).__name__}."
            ),
        )

    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass

        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
