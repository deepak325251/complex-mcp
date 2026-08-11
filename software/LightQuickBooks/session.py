from shortuuid import uuid
from typing import Dict

from quickbooks import QuickbooksSession


class LightQuickBooksSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.quickbooks_session = QuickbooksSession(os_cfg=os_cfg, seed=seed)
