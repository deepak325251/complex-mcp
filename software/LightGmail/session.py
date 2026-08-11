from shortuuid import uuid
from typing import Dict

from gmail import GmailSession


class LightGmailSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.gmail_session = GmailSession(os_cfg=os_cfg, seed=seed)
