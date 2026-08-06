from shortuuid import uuid
from typing import Dict

from google_analytics import GoogleAnalyticsSession


class LightGoogleAnalyticsSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.google_analytics_session = GoogleAnalyticsSession(seed=seed, os_cfg=os_cfg)
