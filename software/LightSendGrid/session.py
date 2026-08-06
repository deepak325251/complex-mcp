from shortuuid import uuid
from typing import Dict

from sendgrid import SendgridSession


class LightSendGridSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.sendgrid_session = SendgridSession(seed=seed, os_cfg=os_cfg)
