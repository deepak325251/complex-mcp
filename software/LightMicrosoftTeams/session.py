from shortuuid import uuid
from typing import Dict

from microsoft_teams import MicrosoftTeamsSession


class LightMicrosoftTeamsSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.microsoft_teams_session = MicrosoftTeamsSession(seed=seed, os_cfg=os_cfg)
