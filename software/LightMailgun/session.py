from shortuuid import uuid
from typing import Dict

from mailgun import MailgunSession


class LightMailgunSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.mailgun_session = MailgunSession(seed=seed, os_cfg=os_cfg)
