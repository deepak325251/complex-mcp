from shortuuid import uuid
from typing import Dict
from drive import DriveSession

class LightDriveSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.drive_session = DriveSession(os_cfg=os_cfg, seed=seed)
