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


# ============================================================
# CHANNEL / PROFILE URL PARSING
# ============================================================

@dataclass
class TikTokChannelInput:
    raw_input: str
    username: str | None = None
    normalized_url: str | None = None
    valid: bool = False
    status: str = "CHUA_XU_LY"


CHANNEL_PATTERN = re.compile(
    r"(?:www\.|m\.)?tiktok\.com/@(?P<username>[a-zA-Z0-9_.-]+)",
    re.IGNORECASE,
)

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_.]+$")


def parse_tiktok_channel_input(raw: str) -> TikTokChannelInput:
    """
    Phan tich va chuan hoa dau vao kenh TikTok:
    - https://www.tiktok.com/@username
    - https://www.tiktok.com/@username/video/123456...
    - @username
    - username
    """
    original = (raw or "").strip()

    if not original:
        return TikTokChannelInput(
            raw_input=original,
            valid=False,
            status="LINK_TRONG",
        )

    # 1. URL video co chua @username
    cleaned = clean_url(original)
    video_match = VIDEO_PATTERN.search(cleaned)
    if video_match:
        username = video_match.group("username").lstrip("@")
        if USERNAME_REGEX.match(username):
            return TikTokChannelInput(
                raw_input=original,
                username=username,
                normalized_url=f"https://www.tiktok.com/@{username}",
                valid=True,
                status="HOP_LE",
            )

    # 2. URL kenh: tiktok.com/@username
    parsed = urlparse(cleaned)
    if parsed.netloc:
        hostname = parsed.netloc.lower()
        allowed_hosts = {
            "www.tiktok.com",
            "tiktok.com",
            "m.tiktok.com",
        }
        if hostname not in allowed_hosts:
            return TikTokChannelInput(
                raw_input=original,
                valid=False,
                status="KHONG_HO_TRO_NEN_TANG",
            )

        channel_match = CHANNEL_PATTERN.search(cleaned)
        if channel_match:
            username = channel_match.group("username").lstrip("@")
            if USERNAME_REGEX.match(username):
                return TikTokChannelInput(
                    raw_input=original,
                    username=username,
                    normalized_url=f"https://www.tiktok.com/@{username}",
                    valid=True,
                    status="HOP_LE",
                )

        return TikTokChannelInput(
            raw_input=original,
            valid=False,
            status="LINK_TIKTOK_KHONG_HOP_LE",
        )

    # Neu chuoi chua tiktok.com ma khong co scheme (e.g. tiktok.com/@abc)
    if "tiktok.com" in original.lower():
        channel_match = CHANNEL_PATTERN.search(original)
        if channel_match:
            username = channel_match.group("username").lstrip("@")
            if USERNAME_REGEX.match(username):
                return TikTokChannelInput(
                    raw_input=original,
                    username=username,
                    normalized_url=f"https://www.tiktok.com/@{username}",
                    valid=True,
                    status="HOP_LE",
                )
        return TikTokChannelInput(
            raw_input=original,
            valid=False,
            status="LINK_TIKTOK_KHONG_HOP_LE",
        )

    # 3. Dang @username hoac username thuan
    candidate = original.lstrip("@").strip().rstrip("/")
    if candidate and USERNAME_REGEX.match(candidate):
        return TikTokChannelInput(
            raw_input=original,
            username=candidate,
            normalized_url=f"https://www.tiktok.com/@{candidate}",
            valid=True,
            status="HOP_LE",
        )

    return TikTokChannelInput(
        raw_input=original,
        valid=False,
        status="LINK_TIKTOK_KHONG_HOP_LE",
    )


def deduplicate_channel_inputs(
    raw_inputs: list[str],
) -> tuple[list[TikTokChannelInput], list[str]]:
    """
    Loc cac kenh trung lap.
    Neu nhap nhieu video cua cung mot creator hoac nhieu bien the cua cung mot kenh,
    chi giu lai mot lan (so sanh case-insensitive theo username).
    """
    unique_items: list[TikTokChannelInput] = []
    duplicate_items: list[str] = []
    seen_keys: set[str] = set()

    for raw in raw_inputs:
        item = parse_tiktok_channel_input(raw)

        if item.valid and item.username:
            key = item.username.lower()
        else:
            key = raw.strip()

        if key in seen_keys:
            duplicate_items.append(raw)
            continue

        seen_keys.add(key)
        unique_items.append(item)

    return unique_items, duplicate_items