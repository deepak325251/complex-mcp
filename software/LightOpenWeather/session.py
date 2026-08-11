from shortuuid import uuid
from typing import Dict

from openweather import OpenweatherSession


class LightOpenWeatherSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.openweather_session = OpenweatherSession(os_cfg=os_cfg, seed=seed)
