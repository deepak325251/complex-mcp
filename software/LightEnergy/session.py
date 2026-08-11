from shortuuid import uuid
from typing import Dict
from energy import EnergySession

class LightEnergySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.energy_session = EnergySession(os_cfg=os_cfg, seed=seed)
