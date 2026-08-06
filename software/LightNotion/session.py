from shortuuid import uuid
from typing import Dict

from notion import NotionSession


class LightNotionSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.notion_session = NotionSession(seed=seed, os_cfg=os_cfg)
