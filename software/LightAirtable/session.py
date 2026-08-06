from shortuuid import uuid
from typing import Dict

from airtable import AirtableSession


class LightAirtableSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.airtable_session = AirtableSession(seed=seed, os_cfg=os_cfg)
