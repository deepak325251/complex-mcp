from shortuuid import uuid
from typing import Dict

from slack import SlackSession


class LightSlackSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.slack_session = SlackSession(seed=seed, os_cfg=os_cfg)
