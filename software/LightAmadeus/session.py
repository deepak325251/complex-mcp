from shortuuid import uuid
from typing import Dict

from amadeus import AmadeusSession


class LightAmadeusSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.amadeus_session = AmadeusSession(seed=seed, os_cfg=os_cfg)
