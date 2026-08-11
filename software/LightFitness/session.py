from shortuuid import uuid
from typing import Dict
from fitness import FitnessSession

class LightFitnessSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.fitness_session = FitnessSession(os_cfg=os_cfg, seed=seed)
