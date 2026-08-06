from shortuuid import uuid
from typing import Dict
from forum import ForumSession

class LightForumSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.forum_session = ForumSession(seed=seed, os_cfg=os_cfg)
