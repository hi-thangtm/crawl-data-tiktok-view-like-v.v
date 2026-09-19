from datetime import datetime
from pathlib import Path

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from app.models import VideoResult
from app.utils.url_parser import parse_tiktok_url
from app.collectors.tiktok_http import (
    extract_json_from_html,
    get_author_data,
    format_release_time,
)


def save_browser_debug(
    video_id: str,
    html: str,
    page=None,
) -> None:

    debug_dir = Path("data/debug")

    debug_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    html_path = debug_dir / f"{video_id}_browser.html"

    html_path.write_text(
        html,
        encoding="utf-8",
    )

    if page is not None:
        try:
            screenshot_path = (
                debug_dir
                / f"{video_id}_browser.png"
            )

            page.screenshot(
                path=str(screenshot_path),
                full_page=True,
            )

        except Exception:
            pass


def detect_visible_page_status(page) -> str | None:
    """
    Chi kiem tra TEXT DANG HIEN THI tren trang.

    Khong quet toan bo HTML vi TikTok co the chua
    cac chuoi nhu 'video unavailable' trong JavaScript,
    gay false positive.
    """

    try:
        body_text = page.locator("body").inner_text(
            timeout=3000
        )

    except Exception:
        return None

    text = body_text.lower()

    unavailable_phrases = [
        "video currently unavailable",
        "video unavailable",
        "this video is unavailable",
        "couldn't find this video",
        "could not find this video",
        "video không khả dụng",
        "video hiện không khả dụng",
        "không tìm thấy video",
    ]

    private_phrases = [
        "this account is private",
        "this video is private",
        "tài khoản này là riêng tư",
        "video này là riêng tư",
    ]

    challenge_phrases = [
        "verify to continue",
        "security verification",
        "captcha",
        "xác minh để tiếp tục",
    ]

    for phrase in challenge_phrases:
        if phrase in text:
            return "ACCESS_CHALLENGE"

    for phrase in private_phrases:
        if phrase in text:
            return "VIDEO_RIENG_TU"

    for phrase in unavailable_phrases:
        if phrase in text:
            return "VIDEO_KHONG_KHA_DUNG"

    return None


def fill_result_from_item(
    result: VideoResult,
    item: dict,
    source: str,
    fallback_username: str | None,
) -> VideoResult:

    stats = item.get(
        "stats",
        {},
    )

    username, uploader = get_author_data(
        item
    )

    result.title = (
        item.get("desc")
        or item.get("title")
        or ""
    )

    result.username = (
        username
        or fallback_username
    )

    result.uploader = (
        uploader
        or result.username
    )

    result.release_time = format_release_time(
        item.get("createTime")
        or item.get("create_time")
    )

    result.view = stats.get(
        "playCount"
    )

    result.like = stats.get(
        "diggCount"
    )

    result.comment = stats.get(
        "commentCount"
    )

    result.share = stats.get(
        "shareCount"
    )

    # Khong dung "or" vi gia tri 0 van la hop le
    if stats.get("collectCount") is not None:
        result.save = stats.get(
            "collectCount"
        )

    elif stats.get("saveCount") is not None:
        result.save = stats.get(
            "saveCount"
        )

    elif stats.get("favoriteCount") is not None:
        result.save = stats.get(
            "favoriteCount"
        )

    result.status = "THANH_CONG"

    result.collector = (
        f"BROWSER/{source}"
    )

    return result


def collect_tiktok_browser(
    url: str,
    headless: bool = True,
) -> VideoResult:

    parsed = parse_tiktok_url(
        url
    )

    retrieval_time = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    result = VideoResult(
        link=url,
        retrieval_time=retrieval_time,
    )

    if not parsed.valid:

        result.status = parsed.status

        return result

    result.video_id = parsed.video_id
    result.username = parsed.username
    result.normalized_url = (
        parsed.normalized_url
    )
    result.collector = "BROWSER"

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=headless,
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            user_agent=(
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/152.0.0.0 "
                "Safari/537.36"
            ),
        )

        page = context.new_page()

        try:

            print()
            print(
                "Dang mo Chromium..."
            )

            print(
                "URL:",
                parsed.normalized_url,
            )

            response = page.goto(
                parsed.normalized_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            if response:
                print(
                    "BROWSER HTTP STATUS:",
                    response.status,
                )

            print(
                "FINAL URL:",
                page.url,
            )

            # Cho TikTok render
            page.wait_for_timeout(
                5000
            )

            # Cho hydration script neu co
            try:

                page.wait_for_selector(
                    "script#__UNIVERSAL_DATA_FOR_REHYDRATION__",
                    timeout=5000,
                )

            except PlaywrightTimeoutError:
                pass

            html = page.content()

            print(
                "BROWSER HTML LENGTH:",
                len(html),
            )

            # ==================================================
            # QUAN TRONG:
            # THU PARSE DU LIEU TRUOC
            # ==================================================

            item, source = extract_json_from_html(
                html,
                parsed.video_id,
            )

            if item:

                print(
                    "TIM THAY VIDEO DATA:",
                    source,
                )

                result = fill_result_from_item(
                    result=result,
                    item=item,
                    source=source,
                    fallback_username=parsed.username,
                )

                return result

            # ==================================================
            # CHI KHI KHONG CO DATA MOI KIEM TRA
            # PRIVATE / UNAVAILABLE / CAPTCHA
            # ==================================================

            detected_status = (
                detect_visible_page_status(
                    page
                )
            )

            if detected_status:

                print(
                    "PAGE STATUS:",
                    detected_status,
                )

                save_browser_debug(
                    parsed.video_id,
                    html,
                    page,
                )

                result.status = (
                    detected_status
                )

                return result

            # ==================================================
            # KHONG CO JSON + KHONG CO LOI RO RANG
            # ==================================================

            print(
                "Khong tim thay JSON video."
            )

            save_browser_debug(
                parsed.video_id,
                html,
                page,
            )

            result.status = (
                "KHONG_TIM_THAY_DU_LIEU_VIDEO"
            )

            return result

        except PlaywrightTimeoutError:

            result.status = (
                "BROWSER_TIMEOUT"
            )

            return result

        except Exception as exc:

            result.status = (
                "LOI_BROWSER:"
                f"{type(exc).__name__}"
            )

            print(
                "BROWSER ERROR:",
                repr(exc),
            )

            return result

        finally:

            try:
                context.close()
            except Exception:
                pass

            try:
                browser.close()
            except Exception:
                pass