from shortuuid import uuid
from typing import Dict
from notes import NotesSession

class LightNotesSession:
    def __init__(
        self,
        seed: int,
        os_cfg: Dict[str, str]
    ):
        self.session_id = f"session_{uuid()}"
        self.notes_session = NotesSession(
            seed=seed,
            os_cfg=os_cfg
        )
