from shortuuid import uuid
from typing import Dict
from learn import LearnSession

class LightLearnSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.learn_session = LearnSession(
            seed=seed,
            os_cfg=os_cfg
        )
