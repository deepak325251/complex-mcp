from shortuuid import uuid
from typing import Dict

from google_maps import GoogleMapsSession


class LightGoogleMapsSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.google_maps_session = GoogleMapsSession(seed=seed, os_cfg=os_cfg)
