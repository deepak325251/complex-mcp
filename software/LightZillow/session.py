from shortuuid import uuid
from typing import Dict

from zillow import ZillowSession


class LightZillowSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.zillow_session = ZillowSession(seed=seed, os_cfg=os_cfg)
