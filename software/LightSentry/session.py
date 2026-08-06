from shortuuid import uuid
from typing import Dict

from sentry import SentrySession


class LightSentrySession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.sentry_session = SentrySession(seed=seed, os_cfg=os_cfg)
