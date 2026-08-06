from shortuuid import uuid
from typing import Dict
from podcast import PodcastSession

class LightPodcastSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.podcast_session = PodcastSession(
            seed=seed,
            os_cfg=os_cfg
        )
