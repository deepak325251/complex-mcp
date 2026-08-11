from shortuuid import uuid
from typing import Dict

from ticketmaster import TicketmasterSession


class LightTicketmasterSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.ticketmaster_session = TicketmasterSession(os_cfg=os_cfg, seed=seed)
