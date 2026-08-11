from shortuuid import uuid
from typing import Dict
from game import GameSession

class LightGameSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.game_session = GameSession(os_cfg=os_cfg, seed=seed)
