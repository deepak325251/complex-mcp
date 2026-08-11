from shortuuid import uuid
from typing import Dict

from linear import LinearSession


class LightLinearSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.linear_session = LinearSession(os_cfg=os_cfg, seed=seed)
