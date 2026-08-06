from shortuuid import uuid
from typing import Dict

from etsy import EtsySession


class LightEtsySession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.etsy_session = EtsySession(seed=seed, os_cfg=os_cfg)
