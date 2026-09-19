import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse


@dataclass
class TikTokURL:
    original_url: str

    normalized_url: str | None = None
    username: str | None = None
    video_id: str | None = None

    valid: bool = False
    status: str = "CHUA_XU_LY"


VIDEO_PATTERN = re.compile(
    r"(?:www\.|m\.)?tiktok\.com/@(?P<username>[^/?]+)/video/(?P<video_id>\d+)",
    re.IGNORECASE,
)


def clean_url(url: str) -> str:
    url = url.strip()

    if not url:
        return ""

    parsed = urlparse(url)

    scheme = parsed.scheme or "https"

    return urlunparse(
        (
            scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            "",
            "",
        )
    )


def parse_tiktok_url(url: str) -> TikTokURL:

    original = url.strip()

    if not original:
        return TikTokURL(
            original_url=original,
            valid=False,
            status="LINK_TRONG",
        )

    cleaned = clean_url(original)

    parsed = urlparse(cleaned)

    hostname = parsed.netloc.lower()

    allowed_hosts = {
        "www.tiktok.com",
        "tiktok.com",
        "m.tiktok.com",
    }

    if hostname not in allowed_hosts:
        return TikTokURL(
            original_url=original,
            valid=False,
            status="KHONG_HO_TRO_NEN_TANG",
        )

    match = VIDEO_PATTERN.search(cleaned)

    if not match:
        return TikTokURL(
            original_url=original,
            normalized_url=cleaned,
            valid=False,
            status="LINK_TIKTOK_KHONG_HOP_LE",
        )

    username = match.group("username")
    video_id = match.group("video_id")

    normalized_url = (
        f"https://www.tiktok.com/@{username}/video/{video_id}"
    )

    return TikTokURL(
        original_url=original,
        normalized_url=normalized_url,
        username=username,
        video_id=video_id,
        valid=True,
        status="HOP_LE",
    )