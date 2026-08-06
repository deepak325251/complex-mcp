from shortuuid import uuid
from typing import Dict

from linear import LinearSession


class LightLinearSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.linear_session = LinearSession(seed=seed, os_cfg=os_cfg)
