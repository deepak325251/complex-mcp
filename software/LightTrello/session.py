from shortuuid import uuid
from typing import Dict

from trello import TrelloSession


class LightTrelloSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.trello_session = TrelloSession(seed=seed, os_cfg=os_cfg)
