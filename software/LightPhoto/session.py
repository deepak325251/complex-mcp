from shortuuid import uuid
from typing import Dict
from photo import PhotoSession

class LightPhotoSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.photo_session = PhotoSession(
            seed=seed,
            os_cfg=os_cfg
        )
