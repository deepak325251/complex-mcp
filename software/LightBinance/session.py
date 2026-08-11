from shortuuid import uuid
from typing import Dict

from binance import BinanceSession


class LightBinanceSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.binance_session = BinanceSession(os_cfg=os_cfg, seed=seed)
