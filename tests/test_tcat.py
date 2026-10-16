"""Core logic, no Home Assistant needed: python -m pytest tests/test_tcat.py (or python tests/test_tcat.py)."""
import sys
from datetime import datetime
from pathlib import Path

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parents[1] / "custom_components" / "tcat")]
from feed import gtfs_zip, trip_updates  # noqa: E402
from tcat import TZ, Gtfs, departures, parse_trip_updates  # noqa: E402

G = Gtfs(gtfs_zip())
NOW = datetime(2026, 10, 16, 7, 55, tzinfo=TZ)


def at(*args):
    return datetime(*args, tzinfo=TZ)


def times(now=NOW, live=b"", stop="BETA|0", walk=0, count=5):
    deps = departures(G, G.runs("R1", stop), parse_trip_updates(live), now, walk, count)
    return [d.time.strftime("%d %H:%M") for d in deps], deps


def test_lines_and_stops():
    assert G.lines() == {"R1": "1 · ALPHA - ÉGLISE"}  # cp1252 decoded, MASQUE route hidden
    assert G.stops_of("R1") == {"ALPHA|0": "ALPHA → ÉGLISE", "BETA|0": "BETA → ÉGLISE",
                                "BETA|1": "BETA → ALPHA", "ÉGLISE|1": "ÉGLISE → ALPHA"}


def test_timetable():
    assert times()[0] == ["16 08:10", "16 08:40", "17 00:40", "17 08:10", "17 08:40"]
    assert times(stop="BETA|1", count=1)[0] == ["16 09:10"]  # other direction, other quay
    assert times(walk=20, count=1)[0] == ["16 08:40"]
    assert times(at(2026, 10, 17, 0, 35), count=1)[0] == ["17 00:40"]  # yesterday's trip after midnight
    assert times(at(2026, 12, 25, 7, 0), count=1)[0] == ["26 08:10"]  # no service on Christmas
    assert times(at(2026, 10, 25, 7, 0), count=1)[0] == ["25 08:10"]  # DST change day


def test_live():
    eight_two = int(at(2026, 10, 16, 8, 2).timestamp())
    t, deps = times(live=trip_updates(("T1", False, [(1, False, eight_two, None)])), count=2)
    assert t == ["16 08:12", "16 08:40"] and deps[0].realtime and deps[0].delay == 120 and not deps[1].realtime
    t, deps = times(live=trip_updates(("T1", False, [(2, False, None, -60)])), count=1)
    assert t == ["16 08:09"] and deps[0].delay == -60
    for gone in [("T1", True, []), ("T1", False, [(2, True, None, None)]), ("T1", False, [(3, False, None, 0)])]:
        assert times(live=trip_updates(gone))[0][:1] == ["16 08:40"]  # cancelled, stop skipped, bus already passed
    assert "17 08:10" in times(live=trip_updates(("T1", True, [])))[0]  # only today's run is cancelled


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
    print("ok")
