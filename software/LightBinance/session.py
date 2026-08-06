from shortuuid import uuid
from typing import Dict

from binance import BinanceSession


class LightBinanceSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.binance_session = BinanceSession(seed=seed, os_cfg=os_cfg)
