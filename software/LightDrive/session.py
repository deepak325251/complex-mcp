from shortuuid import uuid
from typing import Dict
from drive import DriveSession

class LightDriveSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.drive_session = DriveSession(
            seed=seed,
            os_cfg=os_cfg
        )
