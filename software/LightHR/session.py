from shortuuid import uuid
from typing import Dict
from hr import HRSession

class LightHRSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.hr_session = HRSession(
            seed=seed,
            os_cfg=os_cfg
        )
