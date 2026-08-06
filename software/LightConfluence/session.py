from shortuuid import uuid
from typing import Dict

from confluence import ConfluenceSession


class LightConfluenceSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.confluence_session = ConfluenceSession(seed=seed, os_cfg=os_cfg)
