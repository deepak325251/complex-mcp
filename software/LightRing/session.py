from shortuuid import uuid
from typing import Dict

from ring import RingSession


class LightRingSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.ring_session = RingSession(seed=seed, os_cfg=os_cfg)
