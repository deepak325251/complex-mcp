from shortuuid import uuid
from typing import Dict
from mail import MailSession

class LightMailSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.mail_session = MailSession(
            seed=seed,
            os_cfg=os_cfg
        )
