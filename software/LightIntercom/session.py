from shortuuid import uuid
from typing import Dict

from intercom import IntercomSession


class LightIntercomSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.intercom_session = IntercomSession(seed=seed, os_cfg=os_cfg)
