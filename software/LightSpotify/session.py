from shortuuid import uuid
from typing import Dict

from spotify import SpotifySession


class LightSpotifySession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.spotify_session = SpotifySession(seed=seed, os_cfg=os_cfg)
