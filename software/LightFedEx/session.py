from shortuuid import uuid
from typing import Dict

from fedex import FedexSession


class LightFedExSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.fedex_session = FedexSession(seed=seed, os_cfg=os_cfg)
