from shortuuid import uuid
from typing import Dict

from bamboohr import BamboohrSession


class LightBambooHRSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.bamboohr_session = BamboohrSession(seed=seed, os_cfg=os_cfg)
