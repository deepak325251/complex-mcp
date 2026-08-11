from shortuuid import uuid
from typing import Dict

from monday import MondaySession


class LightMondaySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.monday_session = MondaySession(os_cfg=os_cfg, seed=seed)
