from shortuuid import uuid
from typing import Dict

from obsidian import ObsidianSession


class LightObsidianSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.obsidian_session = ObsidianSession(seed=seed, os_cfg=os_cfg)
