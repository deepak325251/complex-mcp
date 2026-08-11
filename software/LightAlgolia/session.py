from shortuuid import uuid
from typing import Dict

from algolia import AlgoliaSession


class LightAlgoliaSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.algolia_session = AlgoliaSession(os_cfg=os_cfg, seed=seed)
