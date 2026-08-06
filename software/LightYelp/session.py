from shortuuid import uuid
from typing import Dict

from yelp import YelpSession


class LightYelpSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.yelp_session = YelpSession(seed=seed, os_cfg=os_cfg)
