from shortuuid import uuid
from typing import Dict

from uber import UberSession


class LightUberSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.uber_session = UberSession(seed=seed, os_cfg=os_cfg)
