from shortuuid import uuid
from typing import Dict

from pinterest import PinterestSession


class LightPinterestSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.pinterest_session = PinterestSession(seed=seed, os_cfg=os_cfg)
