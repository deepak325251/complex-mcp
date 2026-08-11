from shortuuid import uuid
from typing import Dict

from kubernetes import KubernetesSession


class LightKubernetesSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.kubernetes_session = KubernetesSession(os_cfg=os_cfg, seed=seed)
