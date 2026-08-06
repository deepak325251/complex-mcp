from shortuuid import uuid
from typing import Dict
from hotel import HotelSession

class LightHotelSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.hotel_session = HotelSession(
            seed=seed,
            os_cfg=os_cfg
        )
