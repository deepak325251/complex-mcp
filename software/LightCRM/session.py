from shortuuid import uuid
from typing import Dict
from crm import CRMSession

class LightCRMSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.crm_session = CRMSession(
            seed=seed,
            os_cfg=os_cfg
        )
