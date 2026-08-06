from shortuuid import uuid
from typing import Dict

from algolia import AlgoliaSession


class LightAlgoliaSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.algolia_session = AlgoliaSession(seed=seed, os_cfg=os_cfg)
