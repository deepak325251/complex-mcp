from shortuuid import uuid
from typing import Dict

from gusto import GustoSession


class LightGustoSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.gusto_session = GustoSession(seed=seed, os_cfg=os_cfg)
