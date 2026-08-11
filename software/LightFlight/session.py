from shortuuid import uuid
from typing import Dict

from flight import FlightSession


class LightFlightSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.flight_session = FlightSession(os_cfg=os_cfg, seed=seed)
