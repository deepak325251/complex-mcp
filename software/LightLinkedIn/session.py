from shortuuid import uuid
from typing import Dict

from linkedin import LinkedinSession


class LightLinkedInSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.linkedin_session = LinkedinSession(seed=seed, os_cfg=os_cfg)
