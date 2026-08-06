from shortuuid import uuid
from typing import Dict
from tasks import TasksSession

class LightTasksSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.tasks_session = TasksSession(
            seed=seed,
            os_cfg=os_cfg
        )
