from shortuuid import uuid
from typing import Dict

from paypal import PaypalSession


class LightPayPalSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.paypal_session = PaypalSession(seed=seed, os_cfg=os_cfg)
