from shortuuid import uuid
from typing import Dict

from twilio import TwilioSession


class LightTwilioSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.twilio_session = TwilioSession(seed=seed, os_cfg=os_cfg)
