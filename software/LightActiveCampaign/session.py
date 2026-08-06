from shortuuid import uuid
from typing import Dict

from activecampaign import ActiveCampaignSession


class LightActiveCampaignSession:
    def __init__(self, seed: int, os_cfg: Dict[str, str]):
        self.session_id = f"session_{uuid()}"
        self.activecampaign_session = ActiveCampaignSession(seed=seed, os_cfg=os_cfg)
