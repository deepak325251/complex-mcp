from shortuuid import uuid
from typing import Dict

from freshdesk import FreshdeskSession


class LightFreshdeskSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.freshdesk_session = FreshdeskSession(seed=seed, os_cfg=os_cfg)
