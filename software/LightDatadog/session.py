from shortuuid import uuid
from typing import Dict

from datadog import DatadogSession


class LightDatadogSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.datadog_session = DatadogSession(os_cfg=os_cfg, seed=seed)
