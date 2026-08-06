from shortuuid import uuid
from typing import Dict

from openweather import OpenweatherSession


class LightOpenWeatherSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.openweather_session = OpenweatherSession(seed=seed, os_cfg=os_cfg)
