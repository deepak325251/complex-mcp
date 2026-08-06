from shortuuid import uuid
from typing import Dict

from ups import UpsSession


class LightUPSSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.ups_session = UpsSession(seed=seed, os_cfg=os_cfg)
