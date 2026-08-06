from shortuuid import uuid
from typing import Dict

from zoom import ZoomSession


class LightZoomSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.zoom_session = ZoomSession(seed=seed, os_cfg=os_cfg)
