from shortuuid import uuid
from typing import Dict
from tax import TaxSession

class LightTaxSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.tax_session = TaxSession(
            seed=seed,
            os_cfg=os_cfg
        )
