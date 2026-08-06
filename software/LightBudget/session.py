from shortuuid import uuid
from typing import Dict
from budget import BudgetSession

class LightBudgetSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.budget_session = BudgetSession(
            seed=seed,
            os_cfg=os_cfg
        )
