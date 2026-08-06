from shortuuid import uuid
from typing import Dict

from okta import OktaSession


class LightOktaSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.okta_session = OktaSession(seed=seed, os_cfg=os_cfg)
