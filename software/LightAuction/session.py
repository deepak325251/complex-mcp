from shortuuid import uuid
from typing import Dict
from auction import AuctionSession

class LightAuctionSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.auction_session = AuctionSession(seed=seed, os_cfg=os_cfg)
