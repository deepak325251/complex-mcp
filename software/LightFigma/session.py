from shortuuid import uuid
from typing import Dict

from figma import FigmaSession


class LightFigmaSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.figma_session = FigmaSession(os_cfg=os_cfg, seed=seed)
