from shortuuid import uuid
from typing import Dict

from telegram import TelegramSession


class LightTelegramSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.telegram_session = TelegramSession(seed=seed, os_cfg=os_cfg)
