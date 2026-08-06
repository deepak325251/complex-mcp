from shortuuid import uuid
from typing import Dict

from github import GithubSession


class LightGithubSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.github_session = GithubSession(seed=seed, os_cfg=os_cfg)
