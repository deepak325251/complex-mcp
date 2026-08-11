from shortuuid import uuid
from typing import Dict
from learn import LearnSession

class LightLearnSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.learn_session = LearnSession(os_cfg=os_cfg, seed=seed)
