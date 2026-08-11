from shortuuid import uuid
from typing import Dict
from hr import HRSession

class LightHRSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.hr_session = HRSession(os_cfg=os_cfg, seed=seed)
