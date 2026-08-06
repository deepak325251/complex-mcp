from shortuuid import uuid
from typing import Dict

from doordash import DoordashSession


class LightDoorDashSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.doordash_session = DoordashSession(seed=seed, os_cfg=os_cfg)
