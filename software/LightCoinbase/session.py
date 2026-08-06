from shortuuid import uuid
from typing import Dict

from coinbase import CoinbaseSession


class LightCoinbaseSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.coinbase_session = CoinbaseSession(seed=seed, os_cfg=os_cfg)
