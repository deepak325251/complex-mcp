from shortuuid import uuid
from typing import Dict
from security import SecuritySession

class LightSecuritySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.security_session = SecuritySession(os_cfg=os_cfg, seed=seed)
