from shortuuid import uuid
from typing import Dict

from amplitude import AmplitudeSession


class LightAmplitudeSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.amplitude_session = AmplitudeSession(seed=seed, os_cfg=os_cfg)
