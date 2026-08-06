from shortuuid import uuid
from typing import Dict

from segment import SegmentSession


class LightSegmentSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.segment_session = SegmentSession(seed=seed, os_cfg=os_cfg)
