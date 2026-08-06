from shortuuid import uuid
from typing import Dict

from servicenow import ServicenowSession


class LightServiceNowSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.servicenow_session = ServicenowSession(seed=seed, os_cfg=os_cfg)
