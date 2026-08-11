from shortuuid import uuid
from typing import Dict

from weather import WeatherSession

class LightWeatherSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.weather_session = WeatherSession(os_cfg=os_cfg, seed=seed)
