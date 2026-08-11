from shortuuid import uuid
from typing import Dict

from square import SquareSession


class LightSquareSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.square_session = SquareSession(os_cfg=os_cfg, seed=seed)
