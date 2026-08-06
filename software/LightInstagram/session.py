from shortuuid import uuid
from typing import Dict

from instagram import InstagramSession


class LightInstagramSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.instagram_session = InstagramSession(seed=seed, os_cfg=os_cfg)
