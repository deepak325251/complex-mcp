from shortuuid import uuid
from typing import Dict

from wordpress import WordpressSession


class LightWordPressSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.wordpress_session = WordpressSession(os_cfg=os_cfg, seed=seed)
