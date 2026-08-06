from shortuuid import uuid
from typing import Dict

from woocommerce import WoocommerceSession


class LightWooCommerceSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.woocommerce_session = WoocommerceSession(seed=seed, os_cfg=os_cfg)
