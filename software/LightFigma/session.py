from shortuuid import uuid
from typing import Dict

from figma import FigmaSession


class LightFigmaSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.figma_session = FigmaSession(seed=seed, os_cfg=os_cfg)
