from shortuuid import uuid
from typing import Dict

from datadog import DatadogSession


class LightDatadogSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.datadog_session = DatadogSession(seed=seed, os_cfg=os_cfg)
