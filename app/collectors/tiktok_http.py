import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.models import VideoResult
from app.utils.url_parser import parse_tiktok_url


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def to_int(value):
    """
    Chuyen gia tri ve int neu co the.
    TikTok co luc tra number, co luc tra string.
    """

    if value is None:
        return None

    try:
        return int(value)

    except (ValueError, TypeError):
        return None


def find_item_struct(
    obj: Any,
    expected_video_id: str | None = None,
) -> dict | None:
    """
    Tim object video TikTok trong cay JSON.

    Ho tro:
    - stats
    - statsV2

    Video ID co the nam o:
    - id
    - itemId
    - aweme_id
    """

    if isinstance(obj, dict):

        stats = obj.get("stats")
        stats_v2 = obj.get("statsV2")

        has_stats = False

        if isinstance(stats, dict):

            has_stats = any(
                key in stats
                for key in (
                    "playCount",
                    "diggCount",
                    "commentCount",
                    "shareCount",
                )
            )

        if (
            not has_stats
            and isinstance(stats_v2, dict)
        ):

            has_stats = any(
                key in stats_v2
                for key in (
                    "playCount",
                    "diggCount",
                    "commentCount",
                    "shareCount",
                )
            )

        if has_stats:

            object_id = str(
                obj.get("id")
                or obj.get("itemId")
                or obj.get("aweme_id")
                or ""
            )

            if not expected_video_id:
                return obj

            if object_id == str(expected_video_id):
                return obj

        for value in obj.values():

            found = find_item_struct(
                value,
                expected_video_id=expected_video_id,
            )

            if found:
                return found

    elif isinstance(obj, list):

        for value in obj:

            found = find_item_struct(
                value,
                expected_video_id=expected_video_id,
            )

            if found:
                return found

    return None


def get_author_data(
    item: dict,
) -> tuple[str | None, str | None]:
    """
    Tra ve:
    username, uploader
    """

    author = item.get("author")

    username = None
    uploader = None

    if isinstance(author, dict):

        username = (
            author.get("uniqueId")
            or author.get("unique_id")
        )

        uploader = (
            author.get("nickname")
            or author.get("nickName")
            or username
        )

    elif isinstance(author, str):

        username = author
        uploader = author

    author_info = item.get("authorInfo")

    if isinstance(author_info, dict):

        username = (
            username
            or author_info.get("uniqueId")
            or author_info.get("unique_id")
        )

        uploader = (
            uploader
            or author_info.get("nickname")
            or author_info.get("nickName")
            or username
        )

    return username, uploader


def format_release_time(
    value,
) -> str | None:
    """
    Chuyen timestamp TikTok thanh thoi gian doc duoc.
    """

    if value is None:
        return None

    try:

        timestamp = int(value)

        dt = datetime.fromtimestamp(
            timestamp
        )

        return dt.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    except Exception:

        return str(value)


def extract_json_from_html(
    html: str,
    video_id: str,
) -> tuple[dict | None, str | None]:
    """
    Tim video data trong HTML TikTok.

    Thu lan luot:
    1. __UNIVERSAL_DATA_FOR_REHYDRATION__
    2. SIGI_STATE
    3. Cac script JSON khac
    """

    soup = BeautifulSoup(
        html,
        "lxml",
    )

    # =========================================================
    # 1. UNIVERSAL DATA
    # =========================================================

    universal = soup.find(
        "script",
        id="__UNIVERSAL_DATA_FOR_REHYDRATION__",
    )

    if universal:

        text = (
            universal.string
            or universal.get_text()
        )

        if text:

            try:

                data = json.loads(
                    text
                )

                item = find_item_struct(
                    data,
                    expected_video_id=video_id,
                )

                if item:
                    return (
                        item,
                        "UNIVERSAL_DATA",
                    )

            except Exception:
                pass

    # =========================================================
    # 2. SIGI STATE
    # =========================================================

    sigi = soup.find(
        "script",
        id="SIGI_STATE",
    )

    if sigi:

        text = (
            sigi.string
            or sigi.get_text()
        )

        if text:

            try:

                data = json.loads(
                    text
                )

                item = find_item_struct(
                    data,
                    expected_video_id=video_id,
                )

                if item:
                    return (
                        item,
                        "SIGI_STATE",
                    )

            except Exception:
                pass

    # =========================================================
    # 3. GENERIC JSON FALLBACK
    # =========================================================

    for script in soup.find_all(
        "script"
    ):

        text = (
            script.string
            or script.get_text()
        )

        if not text:
            continue

        if (
            "playCount" not in text
            and "diggCount" not in text
        ):
            continue

        text = text.strip()

        if not (
            text.startswith("{")
            or text.startswith("[")
        ):
            continue

        try:

            data = json.loads(
                text
            )

        except Exception:
            continue

        item = find_item_struct(
            data,
            expected_video_id=video_id,
        )

        if item:

            return (
                item,
                "GENERIC_JSON",
            )

    return None, None


def save_debug_html(
    video_id: str,
    html: str,
) -> None:
    """
    Luu HTML neu collector khong parse duoc.
    """

    debug_dir = Path(
        "data/debug"
    )

    debug_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        debug_dir
        / f"{video_id}.html"
    )

    path.write_text(
        html,
        encoding="utf-8",
    )


def fill_result_from_item(
    result: VideoResult,
    item: dict,
    source: str,
    fallback_username: str | None,
) -> VideoResult:
    """
    Chuyen item TikTok thanh VideoResult.
    """

    stats = (
        item.get("stats")
        or item.get("statsV2")
        or {}
    )

    username, uploader = (
        get_author_data(item)
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

    result.release_time = (
        format_release_time(
            item.get("createTime")
            or item.get("create_time")
        )
    )

    result.view = to_int(
        stats.get("playCount")
    )

    result.like = to_int(
        stats.get("diggCount")
    )

    result.comment = to_int(
        stats.get("commentCount")
    )

    result.share = to_int(
        stats.get("shareCount")
    )

    if (
        stats.get("collectCount")
        is not None
    ):

        result.save = to_int(
            stats.get("collectCount")
        )

    elif (
        stats.get("saveCount")
        is not None
    ):

        result.save = to_int(
            stats.get("saveCount")
        )

    elif (
        stats.get("favoriteCount")
        is not None
    ):

        result.save = to_int(
            stats.get("favoriteCount")
        )

    result.status = "THANH_CONG"

    result.collector = source

    return result


def collect_tiktok_http(
    url: str,
) -> VideoResult:
    """
    Fast HTTP collector.

    Neu HTML public khong co data:
    -> CAN_BROWSER_FALLBACK
    """

    parsed = parse_tiktok_url(
        url
    )

    retrieval_time = (
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    result = VideoResult(
        link=url,
        retrieval_time=retrieval_time,
    )

    if not parsed.valid:

        result.status = parsed.status

        return result

    result.video_id = (
        parsed.video_id
    )

    result.username = (
        parsed.username
    )

    result.normalized_url = (
        parsed.normalized_url
    )

    try:

        with httpx.Client(
            headers=HEADERS,
            follow_redirects=True,
            timeout=12.0,
            http2=False,
        ) as client:

            response = client.get(
                parsed.normalized_url
            )

    except Exception as exc:

        result.status = (
            "LOI_HTTP:"
            + type(exc).__name__
        )

        result.collector = "HTTP"

        return result

    print()

    print(
        "HTTP STATUS :",
        response.status_code,
    )

    print(
        "HTML LENGTH :",
        len(response.text),
    )

    print(
        "FINAL URL   :",
        response.url,
    )

    if response.status_code != 200:

        result.status = (
            f"HTTP_{response.status_code}"
        )

        result.collector = "HTTP"

        return result

    html = response.text

    item, source = (
        extract_json_from_html(
            html,
            parsed.video_id,
        )
    )

    if not item:

        save_debug_html(
            parsed.video_id,
            html,
        )

        result.status = (
            "CAN_BROWSER_FALLBACK"
        )

        result.collector = "HTTP"

        return result

    return fill_result_from_item(
        result=result,
        item=item,
        source=f"HTTP/{source}",
        fallback_username=parsed.username,
    )