from shortuuid import uuid
from typing import Dict

from stripe import StripeSession


class LightStripeSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.stripe_session = StripeSession(seed=seed, os_cfg=os_cfg)
