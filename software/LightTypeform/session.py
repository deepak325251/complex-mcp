from shortuuid import uuid
from typing import Dict

from typeform import TypeformSession


class LightTypeformSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.typeform_session = TypeformSession(os_cfg=os_cfg, seed=seed)
