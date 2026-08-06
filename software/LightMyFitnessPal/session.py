from shortuuid import uuid
from typing import Dict

from myfitnesspal import MyfitnesspalSession


class LightMyFitnessPalSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.myfitnesspal_session = MyfitnesspalSession(seed=seed, os_cfg=os_cfg)
