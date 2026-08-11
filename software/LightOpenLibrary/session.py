from shortuuid import uuid
from typing import Dict

from openlibrary import OpenlibrarySession


class LightOpenLibrarySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.openlibrary_session = OpenlibrarySession(os_cfg=os_cfg, seed=seed)
