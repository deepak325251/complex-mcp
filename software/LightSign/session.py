from shortuuid import uuid
from typing import Dict
from sign import SignSession

class LightSignSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.sign_session = SignSession(os_cfg=os_cfg, seed=seed)
