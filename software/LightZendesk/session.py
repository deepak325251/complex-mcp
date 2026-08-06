from shortuuid import uuid
from typing import Dict

from zendesk import ZendeskSession


class LightZendeskSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.zendesk_session = ZendeskSession(seed=seed, os_cfg=os_cfg)
