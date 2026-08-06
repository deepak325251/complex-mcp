from shortuuid import uuid
from typing import Dict

from instacart import InstacartSession


class LightInstacartSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.instacart_session = InstacartSession(seed=seed, os_cfg=os_cfg)
