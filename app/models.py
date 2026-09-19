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