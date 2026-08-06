from shortuuid import uuid
from typing import Dict

from kraken import KrakenSession


class LightKrakenSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.kraken_session = KrakenSession(seed=seed, os_cfg=os_cfg)
