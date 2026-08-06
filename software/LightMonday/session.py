from shortuuid import uuid
from typing import Dict

from monday import MondaySession


class LightMondaySession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.monday_session = MondaySession(seed=seed, os_cfg=os_cfg)
