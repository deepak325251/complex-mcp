from shortuuid import uuid
from typing import Dict

from reddit import RedditSession


class LightRedditSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.reddit_session = RedditSession(os_cfg=os_cfg, seed=seed)
