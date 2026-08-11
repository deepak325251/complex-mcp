import random
from typing import Dict, List, Any
from pathlib import Path
import yaml
import sys
from datetime import datetime

WORK_DIR = Path('.').__str__()
if WORK_DIR not in sys.path:
    sys.path.append(WORK_DIR)

from software.utils.core import OSConnector, DummyOSConnector
from software.utils.world_snapshot import restore_into
from software.utils.time import TimeMachine

CORPUS_PATH = Path(__file__).resolve().parent / "corpus"


def _to_bool(v) -> bool:
    return str(v).strip().lower() == "true"


def _to_int(v) -> int:
    return int(str(v).strip())


def _to_float(v) -> float:
    return float(str(v).strip())


def _split_tags(s) -> List[str]:
    return [t for t in (s or "").split(";") if t]


class TwitchSession:
    """Deterministic sandbox for the Twitch Helix API mock, ported from the FastAPI service.

    State is loaded from the corpus at init; subsequent calls read the in-memory
    tables so repeated calls within a session stay consistent.
    """

    def __init__(self, os_cfg, seed=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        restore_into(self, Path(__file__).resolve().parent / "world.pkl")
        self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def get_session_dict(self):
        return {"users": self.users, "streams": self.streams}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def uuid(self) -> str:
        alphabet = "0123456789"
        return ''.join(self.rng.choices(alphabet, k=16))

    # --- API methods -------------------------------------------------------
    def get_users(self, logins: List[str] | None = None, ids: List[str] | None = None) -> Dict[str, Any]:
        results = list(self.users)
        if logins:
            wanted = {l.strip().lower() for l in logins}
            results = [u for u in results if u["login"].lower() in wanted]
        if ids:
            wanted_ids = {i.strip() for i in ids}
            results = [u for u in results if u["id"] in wanted_ids]
        return {"status": "ok", "output": results}

    def get_streams(self, user_logins: List[str] | None = None, user_ids: List[str] | None = None,
                    game_id: str | None = None) -> Dict[str, Any]:
        results = [s for s in self.streams if s["is_live"]]
        if user_logins:
            wanted = {l.strip().lower() for l in user_logins}
            results = [s for s in results if s["user_login"].lower() in wanted]
        if user_ids:
            wanted_ids = {i.strip() for i in user_ids}
            results = [s for s in results if s["user_id"] in wanted_ids]
        if game_id:
            results = [s for s in results if s["game_id"] == game_id]
        results.sort(key=lambda s: s["viewer_count"], reverse=True)
        return {"status": "ok", "output": results}

    def get_channels(self, broadcaster_ids: List[str]) -> Dict[str, Any]:
        wanted = {i.strip() for i in broadcaster_ids}
        results = [c for c in self.channels if c["broadcaster_id"] in wanted]
        return {"status": "ok", "output": results}

    def get_channel_followers(self, broadcaster_id: str) -> Dict[str, Any]:
        channel = next((c for c in self.channels if c["broadcaster_id"] == broadcaster_id), None)
        if not channel:
            return {"status": "ok", "output": {"data": [], "total": 0}}
        return {"status": "ok", "output": {"data": [], "total": channel["follower_count"]}}

    def get_top_games(self, first: int = 20) -> Dict[str, Any]:
        results = sorted(self.games, key=lambda g: g["rank"])[:first]
        return {"status": "ok", "output": results}

    def get_games(self, names: List[str] | None = None, ids: List[str] | None = None) -> Dict[str, Any]:
        results = list(self.games)
        if names:
            wanted = {n.strip().lower() for n in names}
            results = [g for g in results if g["name"].lower() in wanted]
        if ids:
            wanted_ids = {i.strip() for i in ids}
            results = [g for g in results if g["id"] in wanted_ids]
        return {"status": "ok", "output": results}

    def get_clips(self, broadcaster_id: str | None = None, game_id: str | None = None,
                  first: int = 20) -> Dict[str, Any]:
        results = list(self.clips)
        if broadcaster_id:
            results = [c for c in results if c["broadcaster_id"] == broadcaster_id]
        if game_id:
            results = [c for c in results if c["game_id"] == game_id]
        results.sort(key=lambda c: c["view_count"], reverse=True)
        return {"status": "ok", "output": results[:first]}


if __name__ == "__main__":
    s = TwitchSession(seed=12)
    print(s.get_top_games())
    print(s.get_users(logins=["pixelpaladin"]))
