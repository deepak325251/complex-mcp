from shortuuid import uuid
from typing import Dict

from tmdb import TmdbSession


class LightTMDBSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.tmdb_session = TmdbSession(seed=seed, os_cfg=os_cfg)
