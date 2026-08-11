from shortuuid import uuid
from typing import Dict

from pinterest import PinterestSession


class LightPinterestSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.pinterest_session = PinterestSession(os_cfg=os_cfg, seed=seed)
