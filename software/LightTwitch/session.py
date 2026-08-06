from shortuuid import uuid
from typing import Dict

from twitch import TwitchSession


class LightTwitchSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.twitch_session = TwitchSession(seed=seed, os_cfg=os_cfg)
