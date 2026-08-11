from shortuuid import uuid
from typing import Dict

from intercom import IntercomSession


class LightIntercomSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.intercom_session = IntercomSession(os_cfg=os_cfg, seed=seed)
