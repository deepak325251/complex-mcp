from shortuuid import uuid
from typing import Dict

from docusign import DocusignSession


class LightDocuSignSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.docusign_session = DocusignSession(seed=seed, os_cfg=os_cfg)
