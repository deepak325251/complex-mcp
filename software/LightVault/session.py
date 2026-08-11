from shortuuid import uuid
from typing import Dict
from vault import VaultSession

class LightVaultSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.vault_session = VaultSession(os_cfg=os_cfg, seed=seed)
