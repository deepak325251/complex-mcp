from shortuuid import uuid
from typing import Dict

from hubspot import HubspotSession


class LightHubspotSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.hubspot_session = HubspotSession(seed=seed, os_cfg=os_cfg)
