from shortuuid import uuid
from typing import Dict

from google_calendar import GoogleCalendarSession


class LightGoogleCalendarSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.google_calendar_session = GoogleCalendarSession(seed=seed, os_cfg=os_cfg)
