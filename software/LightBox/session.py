from shortuuid import uuid
from typing import Dict

from box import BoxSession


class LightBoxSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.box_session = BoxSession(seed=seed, os_cfg=os_cfg)
