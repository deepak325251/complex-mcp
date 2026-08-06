from shortuuid import uuid
from typing import Dict

from amazon_seller import AmazonSellerSession


class LightAmazonSellerSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.amazon_seller_session = AmazonSellerSession(seed=seed, os_cfg=os_cfg)
