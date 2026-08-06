from shortuuid import uuid
from typing import Dict

from reddit import RedditSession


class LightRedditSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.reddit_session = RedditSession(seed=seed, os_cfg=os_cfg)
