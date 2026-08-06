from shortuuid import uuid
from typing import Dict

from vimeo import VimeoSession


class LightVimeoSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.vimeo_session = VimeoSession(seed=seed, os_cfg=os_cfg)
