from shortuuid import uuid
from typing import Dict

from google_drive import GoogleDriveSession


class LightGoogleDriveSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.google_drive_session = GoogleDriveSession(seed=seed, os_cfg=os_cfg)
