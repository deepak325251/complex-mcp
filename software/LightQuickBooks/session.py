from shortuuid import uuid
from typing import Dict

from quickbooks import QuickbooksSession


class LightQuickBooksSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.quickbooks_session = QuickbooksSession(seed=seed, os_cfg=os_cfg)
