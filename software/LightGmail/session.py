from shortuuid import uuid
from typing import Dict

from gmail import GmailSession


class LightGmailSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.gmail_session = GmailSession(seed=seed, os_cfg=os_cfg)
