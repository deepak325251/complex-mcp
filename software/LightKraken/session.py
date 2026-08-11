from shortuuid import uuid
from typing import Dict

from kraken import KrakenSession


class LightKrakenSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.kraken_session = KrakenSession(os_cfg=os_cfg, seed=seed)
