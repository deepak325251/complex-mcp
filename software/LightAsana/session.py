from shortuuid import uuid
from typing import Dict

from asana import AsanaSession


class LightAsanaSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.asana_session = AsanaSession(seed=seed, os_cfg=os_cfg)
