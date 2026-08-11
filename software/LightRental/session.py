from shortuuid import uuid
from typing import Dict
from rental import RentalSession

class LightRentalSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.rental_session = RentalSession(os_cfg=os_cfg, seed=seed)
