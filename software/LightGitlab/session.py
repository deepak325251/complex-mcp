from shortuuid import uuid
from typing import Dict

from gitlab import GitlabSession


class LightGitlabSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.gitlab_session = GitlabSession(seed=seed, os_cfg=os_cfg)
