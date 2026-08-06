from shortuuid import uuid
from typing import Dict
from subscription import SubscriptionSession

class LightSubscriptionSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.subscription_session = SubscriptionSession(seed=seed, os_cfg=os_cfg)
