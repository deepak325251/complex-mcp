from shortuuid import uuid
from typing import Dict
from video import VideoSession

class LightVideoSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.video_session = VideoSession(os_cfg=os_cfg, seed=seed)
