from shortuuid import uuid
from typing import Dict

from twitter import TwitterSession


class LightTwitterSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.twitter_session = TwitterSession(seed=seed, os_cfg=os_cfg)
