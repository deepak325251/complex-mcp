from shortuuid import uuid
from typing import Dict

from github import GithubSession


class LightGithubSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.github_session = GithubSession(os_cfg=os_cfg, seed=seed)
