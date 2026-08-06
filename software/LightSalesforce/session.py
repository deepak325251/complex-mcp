from shortuuid import uuid
from typing import Dict

from salesforce import SalesforceSession


class LightSalesforceSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.salesforce_session = SalesforceSession(seed=seed, os_cfg=os_cfg)
