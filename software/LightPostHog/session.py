from shortuuid import uuid
from typing import Dict

from posthog import PosthogSession


class LightPostHogSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.posthog_session = PosthogSession(seed=seed, os_cfg=os_cfg)
