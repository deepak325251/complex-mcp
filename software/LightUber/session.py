from shortuuid import uuid
from typing import Dict

from uber import UberSession


class LightUberSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.uber_session = UberSession(os_cfg=os_cfg, seed=seed)
