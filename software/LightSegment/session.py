from shortuuid import uuid
from typing import Dict

from segment import SegmentSession


class LightSegmentSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.segment_session = SegmentSession(os_cfg=os_cfg, seed=seed)
