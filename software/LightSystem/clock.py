import datetime
import random
from pathlib import Path

from software.utils.world_snapshot import restore_into, seed_mode, resolve_seed

class ClockSession:
    def __init__(self, seed=None):
        # Seedless: clock state (frozen `_now` + post-init rng) is loaded from a
        # snapshot beside this module; `seed` accepted for client compat, ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self._now = self._init_now()
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "clock_world.pkl")
    
    def now(self):
        return {
            "status": "ok",
            "output": str(self._now)
        }
    
    def step(self):
        self._now += datetime.timedelta(seconds=self.rng.randint(1, 10))
        return self.now()

    def _init_now(self, year: int = 2026) -> datetime.datetime:
        start = datetime.datetime(year, 1, 1, 0, 0, 0)
        next_year = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
        seconds_in_year = int((next_year - start).total_seconds())
        offset = self.rng.randrange(seconds_in_year)

        return start + datetime.timedelta(seconds=offset)
    
    def gen_past(self, start_year: int = 2015, k: int = 1) -> list[str]:
        if k <= 0:
            return []
        start = datetime.datetime(start_year, 1, 1, 0, 0, 0)
        end = self._now
        if start >= end:
            return [str(end)] * k

        seconds_range = int((end - start).total_seconds())
        timestamps = []
        for _ in range(k):
            offset = self.rng.randrange(seconds_range + 1)
            timestamps.append(start + datetime.timedelta(seconds=offset))

        timestamps.sort()
        return {
            "status": "ok",
            "output": [str(ts) for ts in timestamps]
        }


if __name__ == "__main__":
    clock_session = ClockSession(seed=1)

    print(clock_session.now())
