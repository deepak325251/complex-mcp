from shortuuid import uuid
from typing import Dict
from podcast import PodcastSession

class LightPodcastSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.podcast_session = PodcastSession(os_cfg=os_cfg, seed=seed)
