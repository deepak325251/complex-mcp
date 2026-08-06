from shortuuid import uuid
from typing import Dict

from klaviyo import KlaviyoSession


class LightKlaviyoSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.klaviyo_session = KlaviyoSession(seed=seed, os_cfg=os_cfg)
