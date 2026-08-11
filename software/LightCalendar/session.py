from shortuuid import uuid
from typing import Dict
from calendar_data import CalendarSession

class LightCalendarSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.calendar_session = CalendarSession(os_cfg=os_cfg, seed=seed)
