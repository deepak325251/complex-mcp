from shortuuid import uuid
from typing import Dict

from ticketmaster import TicketmasterSession


class LightTicketmasterSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.ticketmaster_session = TicketmasterSession(seed=seed, os_cfg=os_cfg)
