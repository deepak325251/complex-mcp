from shortuuid import uuid
from typing import Dict

from youtube import YoutubeSession


class LightYouTubeSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.youtube_session = YoutubeSession(seed=seed, os_cfg=os_cfg)
