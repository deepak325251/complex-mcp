from shortuuid import uuid
from typing import Dict

from sentry import SentrySession


class LightSentrySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.sentry_session = SentrySession(os_cfg=os_cfg, seed=seed)
