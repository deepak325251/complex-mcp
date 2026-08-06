from shortuuid import uuid
from typing import Dict
from game import GameSession

class LightGameSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.game_session = GameSession(
            seed=seed,
            os_cfg=os_cfg
        )
