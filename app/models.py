from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class VideoResult:
    link: str

    title: Optional[str] = None
    uploader: Optional[str] = None
    username: Optional[str] = None

    release_time: Optional[str] = None

    view: Optional[int] = None
    like: Optional[int] = None
    comment: Optional[int] = None
    share: Optional[int] = None
    save: Optional[int] = None

    retrieval_time: Optional[str] = None

    status: str = "CHO_XU_LY"

    video_id: Optional[str] = None
    normalized_url: Optional[str] = None

    collector: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class TikTokProfileResult:
    input_url: str

    profile_url: Optional[str] = None
    username: Optional[str] = None
    nickname: Optional[str] = None
    user_id: Optional[str] = None
    sec_uid: Optional[str] = None
    bio: Optional[str] = None

    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    likes_count: Optional[int] = None
    video_count: Optional[int] = None

    verified: Optional[bool] = None
    private_account: Optional[bool] = None

    avatar_url: Optional[str] = None
    bio_website_url: Optional[str] = None

    collected_at: Optional[str] = None
    status: str = "CHO_XU_LY"
    source_method: Optional[str] = None
    stats_precision: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self):
        return asdict(self)