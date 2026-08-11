from shortuuid import uuid
from typing import Dict

from google_calendar import GoogleCalendarSession


class LightGoogleCalendarSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.google_calendar_session = GoogleCalendarSession(os_cfg=os_cfg, seed=seed)
