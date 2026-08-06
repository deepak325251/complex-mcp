from shortuuid import uuid
from typing import Dict
from food import FoodSession

class LightFoodSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.food_session = FoodSession(
            seed=seed,
            os_cfg=os_cfg
        )
