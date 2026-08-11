from shortuuid import uuid
from typing import Dict

from posthog import PosthogSession


class LightPostHogSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.posthog_session = PosthogSession(os_cfg=os_cfg, seed=seed)
