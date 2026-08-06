from shortuuid import uuid
from typing import Dict

from pagerduty import PagerDutySession


class LightPagerDutySession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.pagerduty_session = PagerDutySession(seed=seed, os_cfg=os_cfg)
