"""Next TCAT (Troyes) buses from the network's open data: GTFS timetable + GTFS-RT live updates.

No Home Assistant imports, so it also runs on its own:
    python tcat.py                      lines
    python tcat.py 3                    stops of line 3 (and their keys)
    python tcat.py 3 "BARBEREY|0" [5]   next buses at that stop, optionally skipping those you can't reach in 5 min
"""
from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Dataset: https://transport.data.gouv.fr/datasets/donnees-tcat-troyes-champagne-metropole-1 (Licence Ouverte 2.0)
GTFS_URL = "https://transport.data.gouv.fr/resources/79847/download"  # always redirects to the current file
TRIP_UPDATES_URL = "http://94.143.218.42:13486/ProfilGtfsRt2_0RSProducer-TCAT/TripUpdate.pb"
TZ = ZoneInfo("Europe/Paris")
HIDDEN_AGENCY = "MASQUE"  # TCAT's internal routes (relief buses, workshop...)
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
RT_MATCH = timedelta(hours=3)  # the feed has no start_date: a live update only applies to the nearest run of a trip


@dataclass
class Departure:
    time: datetime
    terminus: str
    realtime: bool
    delay: int | None  # seconds late (negative: early), None without live data


@dataclass
class Run:
    """One trip serving the chosen stop."""
    trip_id: str
    service_id: str
    seq: int
    secs: int  # GTFS time, can exceed 24 h
    terminus: str
    times: dict[int, int]  # the trip's stop_sequence -> secs, to carry a delay forward


class Gtfs:
    def __init__(self, data: bytes):
        self.zip = zipfile.ZipFile(io.BytesIO(data))
        self.routes = {r["route_id"]: r for r in self._rows("routes.txt") if r.get("agency_id") != HIDDEN_AGENCY}
        self.stops = {s["stop_id"]: s["stop_name"] for s in self._rows("stops.txt")}
        self.trips = {t["trip_id"]: t for t in self._rows("trips.txt") if t["route_id"] in self.routes}
        self.calendar = self._rows("calendar.txt")
        self.exceptions = defaultdict(list)
        for d in self._rows("calendar_dates.txt"):
            self.exceptions[d["date"]].append(d)
        used = {t["route_id"] for t in self.trips.values()}
        self.routes = {k: r for k, r in self.routes.items() if k in used}
        self._timetables: dict[str, dict[str, list[tuple[int, str, int]]]] = {}

    def _rows(self, name: str) -> list[dict[str, str]]:
        if name not in self.zip.namelist():
            return []
        raw = self.zip.read(name)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")  # TCAT's export
        return list(csv.DictReader(io.StringIO(text)))

    def lines(self) -> dict[str, str]:
        """route_id -> "3 · ST JULIEN>BARBEREY", in line order."""
        def order(r):
            n = r["route_short_name"]
            return (not n.isdigit(), int(n) if n.isdigit() else 0, n)
        return {r["route_id"]: f'{r["route_short_name"]} · {r["route_long_name"]}'.strip(" ·")
                for r in sorted(self.routes.values(), key=order)}

    def timetable(self, route_id: str) -> dict[str, list[tuple[int, str, int]]]:
        """trip_id -> [(stop_sequence, stop_id, secs)] for one line. Reads stop_times.txt, so run it off the event loop."""
        if route_id not in self._timetables:
            trips = {k for k, t in self.trips.items() if t["route_id"] == route_id}
            out = defaultdict(list)
            for r in self._rows("stop_times.txt"):
                if r["trip_id"] in trips:
                    out[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"],
                                              secs(r["departure_time"] or r["arrival_time"])))
            for stops in out.values():
                stops.sort()
            self._timetables[route_id] = dict(out)
        return self._timetables[route_id]

    def _direction(self, trip_id: str, stops) -> str:
        return self.trips[trip_id]["direction_id"] or self.stops[stops[-1][1]]

    def stops_of(self, route_id: str) -> dict[str, str]:
        """"STOP|direction" -> "STOP → TERMINUS", for every stop you can board on that line."""
        termini = defaultdict(Counter)
        for trip_id, stops in self.timetable(route_id).items():
            d, end = self._direction(trip_id, stops), self.stops[stops[-1][1]]
            for _, stop_id, _ in stops[:-1]:
                termini[f"{self.stops[stop_id]}|{d}"][end] += 1
        return {k: f'{k.split("|")[0]} → {" / ".join(t for t, _ in c.most_common())}'
                for k, c in sorted(termini.items())}

    def runs(self, route_id: str, stop_key: str) -> list[Run]:
        name, direction = stop_key.split("|", 1)
        out = []
        for trip_id, stops in self.timetable(route_id).items():
            if self._direction(trip_id, stops) != direction:
                continue
            times = {seq: s for seq, _, s in stops}
            for seq, stop_id, s in stops[:-1]:
                if self.stops[stop_id] == name:
                    out.append(Run(trip_id, self.trips[trip_id]["service_id"], seq, s,
                                   self.stops[stops[-1][1]], times))
        return out

    def services(self, day: date) -> set[str]:
        ymd = day.strftime("%Y%m%d")
        on = {c["service_id"] for c in self.calendar
              if c["start_date"] <= ymd <= c["end_date"] and c[DAYS[day.weekday()]] == "1"}
        for e in self.exceptions.get(ymd, ()):
            (on.add if e["exception_type"] == "1" else on.discard)(e["service_id"])
        return on


def secs(hms: str) -> int:
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def departures(gtfs: Gtfs, runs: list[Run], live: dict, now: datetime, walk: int = 0, count: int = 5) -> list[Departure]:
    """The next `count` buses leaving at least `walk` minutes from now. `live` comes from parse_trip_updates."""
    earliest = now + timedelta(minutes=walk)
    out = []
    for offset in (-1, 0, 1):  # yesterday's late trips (after 24:00), today, tomorrow morning
        day = now.astimezone(TZ).date() + timedelta(days=offset)
        services = gtfs.services(day)
        base = datetime.combine(day, time(12), TZ).astimezone(UTC) - timedelta(hours=12)  # GTFS "noon minus 12h"
        for r in runs:
            if r.service_id not in services:
                continue
            planned = base + timedelta(seconds=r.secs)
            delay = None
            if r.trip_id in live and abs(planned - now) < RT_MATCH:
                delay = live_delay(r, live[r.trip_id], base)
                if delay is False:
                    continue  # cancelled, stop skipped, or already passed
            when = planned + timedelta(seconds=delay or 0)
            if when >= earliest:
                out.append(Departure(when.astimezone(TZ), r.terminus, delay is not None, delay))
    return sorted(out, key=lambda d: d.time)[:count]


def live_delay(run: Run, update: dict, base: datetime) -> int | None | bool:
    """Seconds late at the run's stop, None if the update says nothing about it, False if the bus won't stop there."""
    if update["canceled"]:
        return False
    before = None
    for seq, skipped, t, delay in update["stops"]:
        if seq == run.seq:
            if skipped:
                return False
            if t is not None:
                return round(t - (base.timestamp() + run.secs))
            if delay is not None:
                return delay
        if seq < run.seq and seq in run.times and (t is not None or delay is not None):
            before = delay if t is None else round(t - (base.timestamp() + run.times[seq]))
    if before is not None:
        return before  # GTFS-RT: a delay carries on to the next stops
    if update["stops"] and min(s[0] for s in update["stops"]) > run.seq:
        return False  # the update only lists stops after ours: the bus has gone
    return None


# --- GTFS-RT: a tiny protobuf wire-format reader, enough for TripUpdate (avoids pinning protobuf inside HA) ---

def _varint(b: bytes, i: int) -> tuple[int, int]:
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def _fields(b: bytes):
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        f, wire = key >> 3, key & 7
        if wire == 0:
            v, i = _varint(b, i)
        elif wire == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        elif wire == 1:
            v, i = b[i:i + 8], i + 8
        elif wire == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        yield f, v


def _int(v: int) -> int:
    return v - (1 << 64) if v >= 1 << 63 else v  # int32/int64 negatives are 10-byte varints


def parse_trip_updates(data: bytes) -> dict[str, dict]:
    """trip_id -> {"canceled": bool, "stops": [(stop_sequence, skipped, time or None, delay or None)]}."""
    out = {}
    for f, entity in _fields(data):
        if f != 2:  # FeedMessage.entity
            continue
        for f2, tu in _fields(entity):
            if f2 != 3:  # FeedEntity.trip_update
                continue
            trip_id, canceled, stops = None, False, []
            for f3, v in _fields(tu):
                if f3 == 1:  # TripDescriptor
                    d = dict(_fields(v))
                    trip_id = d.get(1, b"").decode("utf-8", "replace")
                    canceled = d.get(4) == 3  # ScheduleRelationship.CANCELED
                elif f3 == 2:  # StopTimeUpdate
                    s = dict(_fields(v))
                    event = dict(_fields(s.get(3) or s.get(2) or b""))  # departure, else arrival
                    stops.append((s.get(1, -1), s.get(5) == 1,
                                  _int(event[2]) if 2 in event else None, _int(event[1]) if 1 in event else None))
            if trip_id:
                out[trip_id] = {"canceled": canceled, "stops": stops}
    return out


if __name__ == "__main__":
    import sys
    import urllib.request

    get = lambda url: urllib.request.urlopen(url, timeout=60).read()
    g = Gtfs(get(GTFS_URL))
    if len(sys.argv) == 1:
        for k, v in g.lines().items():
            print(f"{k:>6}  {v}")
        sys.exit()
    route = next((k for k, r in g.routes.items() if sys.argv[1] in (k, r["route_short_name"])), None)
    if route is None:
        sys.exit(f"unknown line {sys.argv[1]}")
    if len(sys.argv) == 2:
        for k, v in g.stops_of(route).items():
            print(f"{k:<40}  {v}")
        sys.exit()
    runs = g.runs(route, sys.argv[2])
    if not runs:
        sys.exit(f"unknown stop {sys.argv[2]}: pick a key from `python tcat.py {sys.argv[1]}`")
    live = parse_trip_updates(get(TRIP_UPDATES_URL))
    walk = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    for d in departures(g, runs, live, datetime.now(UTC), walk):
        late = "" if d.delay is None else f"  live, {round(d.delay / 60):+d} min" if abs(d.delay) >= 60 else "  live"
        print(f"{d.time:%a %H:%M}  → {d.terminus}{late}")
