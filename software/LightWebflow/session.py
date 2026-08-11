from shortuuid import uuid
from typing import Dict

from webflow import WebflowSession


class LightWebflowSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.webflow_session = WebflowSession(os_cfg=os_cfg, seed=seed)
