from shortuuid import uuid
from typing import Dict

from mailchimp import MailchimpSession


class LightMailchimpSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.mailchimp_session = MailchimpSession(seed=seed, os_cfg=os_cfg)
