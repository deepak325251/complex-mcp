from shortuuid import uuid
from typing import Dict

from wordpress import WordpressSession


class LightWordPressSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.wordpress_session = WordpressSession(seed=seed, os_cfg=os_cfg)
