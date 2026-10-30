import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.models import TikTokProfileResult
from app.utils.url_parser import parse_tiktok_channel_input, TikTokChannelInput


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def parse_count_value(val: Any) -> tuple[int | None, str | None]:
    """
    Chuyen doi so lieu dem ve (int, precision).
    Tra ve (count_int, 'exact' | 'rounded' | None).
    Khong bao gio tu bien None hoac thieu thanh 0.
    """
    if val is None or val == "":
        return None, None

    if isinstance(val, (int, float)):
        return int(val), "exact"

    if isinstance(val, str):
        cleaned = val.strip().replace(",", "")
        if cleaned.isdigit():
            return int(cleaned), "exact"

        # Xu ly dang viet tat neu co nhu 1.2M, 500K
        multiplier = 1
        unit = cleaned[-1].upper() if cleaned else ""
        if unit == "K":
            multiplier = 1_000
            cleaned = cleaned[:-1]
        elif unit == "M":
            multiplier = 1_000_000
            cleaned = cleaned[:-1]
        elif unit == "B":
            multiplier = 1_000_000_000
            cleaned = cleaned[:-1]

        try:
            parsed_float = float(cleaned)
            return int(parsed_float * multiplier), "rounded"
        except (ValueError, TypeError):
            return None, None

    return None, None


def _matches_username(user_dict: dict, expected_username: str | None) -> bool:
    if not expected_username:
        return True
    uid = user_dict.get("uniqueId") or user_dict.get("unique_id")
    if uid:
        return uid.lower() == expected_username.lower()
    raw_id = user_dict.get("id")
    if raw_id and str(raw_id) == str(expected_username):
        return True
    return False


def find_user_info_struct(
    obj: Any,
    expected_username: str | None = None,
) -> tuple[dict | None, dict | None, dict | None, str | None]:
    """
    Tim kiem user va stats/statsV2 trong cay JSON TikTok.
    Ho tro:
    - __UNIVERSAL_DATA_FOR_REHYDRATION__ (__DEFAULT_SCOPE__ -> webapp.user-detail -> userInfo)
    - SIGI_STATE (UserModule)
    - __NEXT_DATA__
    """
    if not isinstance(obj, dict):
        return None, None, None, None

    # 1. Thu tim theo cau truc chuan __DEFAULT_SCOPE__
    default_scope = obj.get("__DEFAULT_SCOPE__")
    if isinstance(default_scope, dict):
        user_detail = default_scope.get("webapp.user-detail")
        if isinstance(user_detail, dict):
            status_code = user_detail.get("statusCode")
            if status_code in {10202, 10204, 10221, 10222}:
                # Ma loi TikTok the hien user khong ton tai hoac bi xoa
                return None, None, None, "NOT_FOUND"

            user_info = user_detail.get("userInfo")
            if isinstance(user_info, dict):
                user = user_info.get("user")
                stats_v2 = user_info.get("statsV2")
                stats = user_info.get("stats")
                if isinstance(user, dict) and (user.get("id") or user.get("uniqueId")):
                    if _matches_username(user, expected_username):
                        return user, stats_v2, stats, "UNIVERSAL_DATA"

    # 2. Thu tim truc tiep key userInfo
    if "userInfo" in obj and isinstance(obj["userInfo"], dict):
        user_info = obj["userInfo"]
        user = user_info.get("user")
        stats_v2 = user_info.get("statsV2")
        stats = user_info.get("stats")
        if isinstance(user, dict) and (user.get("id") or user.get("uniqueId")):
            if _matches_username(user, expected_username):
                return user, stats_v2, stats, "USER_INFO_DIRECT"

    # 3. Thu SIGI_STATE
    user_module = obj.get("UserModule")
    if isinstance(user_module, dict):
        users = user_module.get("users")
        stats_map = user_module.get("stats")
        if isinstance(users, dict) and users:
            target_key = None
            if expected_username:
                for k, u in users.items():
                    if isinstance(u, dict) and _matches_username(u, expected_username):
                        target_key = k
                        break
                    elif str(k).lower() == expected_username.lower():
                        target_key = k
                        break
            else:
                target_key = next(iter(users))

            if target_key is not None:
                user = users.get(target_key)
                stats = stats_map.get(target_key) if isinstance(stats_map, dict) else None
                if isinstance(user, dict):
                    return user, None, stats, "SIGI_STATE"

    # 4. De quy tim dict co chua 'user' va 'stats' hoac 'statsV2'
    for k, v in obj.items():
        if isinstance(v, dict):
            if "user" in v and ("stats" in v or "statsV2" in v):
                user = v.get("user")
                if isinstance(user, dict) and (user.get("id") or user.get("uniqueId")):
                    if _matches_username(user, expected_username):
                        return user, v.get("statsV2"), v.get("stats"), f"NESTED_{k}"
            res_user, res_s2, res_s, res_src = find_user_info_struct(v, expected_username=expected_username)
            if res_user:
                return res_user, res_s2, res_s, res_src

    return None, None, None, None


def extract_profile_from_html(
    html: str,
    expected_username: str | None = None,
) -> tuple[dict | None, dict | None, dict | None, str | None]:
    """
    Trich xuat user, statsV2, stats tu ma HTML trang TikTok.
    """
    if not html:
        return None, None, None, None

    soup = BeautifulSoup(html, "html.parser")

    # 1. script#__UNIVERSAL_DATA_FOR_REHYDRATION__
    script_universal = soup.find(
        "script",
        id="__UNIVERSAL_DATA_FOR_REHYDRATION__",
    )
    if script_universal:
        text_content = (script_universal.string or script_universal.get_text() or "").strip()
        if text_content:
            try:
                data = json.loads(text_content, strict=False)
                u, s2, s, src = find_user_info_struct(data, expected_username=expected_username)
                if u:
                    return u, s2, s, src or "UNIVERSAL_DATA"
                if src == "NOT_FOUND":
                    return None, None, None, "NOT_FOUND"
            except Exception:
                pass

    # 2. script#SIGI_STATE
    script_sigi = soup.find("script", id="SIGI_STATE")
    if script_sigi:
        text_content = (script_sigi.string or script_sigi.get_text() or "").strip()
        if text_content:
            try:
                data = json.loads(text_content, strict=False)
                u, s2, s, src = find_user_info_struct(data, expected_username=expected_username)
                if u:
                    return u, s2, s, src or "SIGI_STATE"
            except Exception:
                pass

    # 3. script#__NEXT_DATA__
    script_next = soup.find("script", id="__NEXT_DATA__")
    if script_next:
        text_content = (script_next.string or script_next.get_text() or "").strip()
        if text_content:
            try:
                data = json.loads(text_content, strict=False)
                u, s2, s, src = find_user_info_struct(data, expected_username=expected_username)
                if u:
                    return u, s2, s, src or "NEXT_DATA"
            except Exception:
                pass


    # Kiem tra text the hien user khong ton tai
    text_lower = soup.get_text().lower()
    not_found_phrases = [
        "couldn't find this account",
        "could not find this account",
        "không tìm thấy tài khoản",
        "không thể tìm thấy tài khoản",
        "user not found",
    ]
    for phrase in not_found_phrases:
        if phrase in text_lower:
            return None, None, None, "NOT_FOUND"

    return None, None, None, None


def build_profile_result_from_data(
    input_url: str,
    normalized_url: str,
    user_node: dict,
    stats_v2: dict | None,
    stats_node: dict | None,
    source_method: str,
    target_username: str | None = None,
) -> TikTokProfileResult:
    """
    Anh xa thong tin tu user node va stats/statsV2 vao TikTokProfileResult.
    Bao toan Unicode, emoji, newline trong bio.
    user_id va sec_uid luon la string.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    result = TikTokProfileResult(
        input_url=input_url,
        profile_url=normalized_url,
        collected_at=now_str,
        source_method=source_method,
    )

    # 1. Thong tin user co ban
    raw_uid = user_node.get("id")
    result.user_id = str(raw_uid) if raw_uid is not None else None

    raw_sec_uid = user_node.get("secUid") or user_node.get("sec_uid")
    result.sec_uid = str(raw_sec_uid) if raw_sec_uid is not None else None

    result.username = (
        user_node.get("uniqueId")
        or user_node.get("unique_id")
        or target_username
    )

    result.nickname = user_node.get("nickname")

    # Bio: giu nguyen unicode, emoji va newline, khong lam bien dang
    raw_bio = user_node.get("signature")
    result.bio = raw_bio if raw_bio is not None else None

    if "verified" in user_node:
        result.verified = bool(user_node.get("verified"))

    # Private account
    is_private = user_node.get("privateAccount")
    if is_private is None:
        is_private = user_node.get("secret")
    if is_private is not None:
        result.private_account = bool(is_private)

    # Avatar URL
    result.avatar_url = (
        user_node.get("avatarLarger")
        or user_node.get("avatarMedium")
        or user_node.get("avatarThumb")
        or user_node.get("avatar_larger")
    )

    # Website in bio
    bio_link = user_node.get("bioLink")
    if isinstance(bio_link, dict):
        result.bio_website_url = bio_link.get("link")
    elif isinstance(bio_link, str) and bio_link.strip():
        result.bio_website_url = bio_link.strip()

    # 2. Chi so thong ke (Uu tien statsV2, fallback stats)
    stats_dict = stats_v2 if isinstance(stats_v2, dict) else (stats_node if isinstance(stats_node, dict) else {})
    using_v2 = isinstance(stats_v2, dict) and bool(stats_v2)

    # Follower
    val_follower = stats_dict.get("followerCount") if "followerCount" in stats_dict else stats_dict.get("follower_count")
    f_val, f_prec = parse_count_value(val_follower)
    result.follower_count = f_val

    # Following
    val_following = stats_dict.get("followingCount") if "followingCount" in stats_dict else stats_dict.get("following_count")
    fing_val, fing_prec = parse_count_value(val_following)
    result.following_count = fing_val

    # Likes: TikTok dung heartCount hoac heart_count cho tong luot thich cua kenh
    # Tuyet doi khong lay diggCount vi do la so video nguoi dung da thich (liked by user)
    val_likes = (
        stats_dict.get("heartCount")
        if "heartCount" in stats_dict
        else stats_dict.get("heart_count")
    )
    l_val, l_prec = parse_count_value(val_likes)
    result.likes_count = l_val

    # Videos
    val_videos = stats_dict.get("videoCount") if "videoCount" in stats_dict else stats_dict.get("video_count")
    v_val, v_prec = parse_count_value(val_videos)
    result.video_count = v_val

    # Do chinh xac precision
    precisions = [p for p in (f_prec, fing_prec, l_prec, v_prec) if p]
    if "rounded" in precisions:
        result.stats_precision = "rounded"
    elif "exact" in precisions or using_v2:
        result.stats_precision = "exact"
    else:
        result.stats_precision = None

    # 3. Danh gia trang thai
    if result.private_account is True and result.follower_count is None:
        result.status = "PRIVATE"
    elif result.username and result.follower_count is not None:
        result.status = "SUCCESS"
    elif result.username or result.user_id:
        result.status = "PARTIAL"
    else:
        result.status = "PARSE_ERROR"

    return result


def collect_profile_http(
    channel_input: str | TikTokChannelInput,
    client: httpx.Client | None = None,
) -> TikTokProfileResult:
    """
    Thu thap thong tin kenh TikTok bang Fast HTTP (httpx + BeautifulSoup).
    """
    if isinstance(channel_input, str):
        parsed = parse_tiktok_channel_input(channel_input)
    else:
        parsed = channel_input

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    result = TikTokProfileResult(
        input_url=parsed.raw_input,
        profile_url=parsed.normalized_url,
        username=parsed.username,
        collected_at=now_str,
        source_method="HTTP",
    )

    if not parsed.valid:
        result.status = parsed.status
        result.error_message = f"Link/username không hợp lệ ({parsed.status})"
        return result

    should_close_client = False
    if client is None:
        client = httpx.Client(
            headers=HEADERS,
            follow_redirects=True,
            timeout=12.0,
            http2=False,
        )
        should_close_client = True

    try:
        response = client.get(parsed.normalized_url)
    except httpx.TimeoutException:
        result.status = "TIMEOUT"
        result.error_message = "HTTP request timeout"
        return result
    except Exception as exc:
        result.status = "NETWORK_ERROR"
        result.error_message = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        if should_close_client:
            client.close()

    # Kiem tra status code
    if response.status_code == 404:
        result.status = "NOT_FOUND"
        result.error_message = "TikTok phản hồi 404 Not Found"
        return result

    if response.status_code in {403, 429}:
        result.status = "RATE_LIMITED"
        result.error_message = f"TikTok phản hồi HTTP {response.status_code}"
        return result

    if response.status_code != 200:
        result.status = f"HTTP_{response.status_code}"
        result.error_message = f"HTTP status {response.status_code}"
        return result

    html = response.text
    user_node, stats_v2, stats_node, source = extract_profile_from_html(
        html,
        expected_username=parsed.username,
    )

    if source == "NOT_FOUND":
        result.status = "NOT_FOUND"
        result.error_message = "Không tìm thấy hồ sơ hoặc tài khoản đã bị khóa"
        return result

    if not user_node:
        # Khong trich xuat duoc JSON bang HTTP, can Browser fallback
        result.status = "CAN_BROWSER_FALLBACK"
        result.error_message = "HTTP không có dữ liệu JSON hồ sơ"
        return result

    return build_profile_result_from_data(
        input_url=parsed.raw_input,
        normalized_url=parsed.normalized_url or f"https://www.tiktok.com/@{parsed.username}",
        user_node=user_node,
        stats_v2=stats_v2,
        stats_node=stats_node,
        source_method=f"HTTP/{source}",
        target_username=parsed.username,
    )
