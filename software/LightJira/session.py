from shortuuid import uuid
from typing import Dict

from jira import JiraSession


class LightJiraSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.jira_session = JiraSession(seed=seed, os_cfg=os_cfg)
