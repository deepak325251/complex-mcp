from shortuuid import uuid
from typing import Dict
from vault import VaultSession

class LightVaultSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.vault_session = VaultSession(
            seed=seed,
            os_cfg=os_cfg
        )
