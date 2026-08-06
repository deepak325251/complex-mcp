from shortuuid import uuid
from typing import Dict

from cloudflare import CloudflareSession


class LightCloudflareSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.cloudflare_session = CloudflareSession(seed=seed, os_cfg=os_cfg)
