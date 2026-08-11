from shortuuid import uuid
from typing import Dict

from whatsapp import WhatsappSession


class LightWhatsAppSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.whatsapp_session = WhatsappSession(os_cfg=os_cfg, seed=seed)
