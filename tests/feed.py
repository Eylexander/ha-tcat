"""A tiny TCAT-like network for the tests: line 1, ALPHA → BETA → ÉGLISE and back, every day."""
import io
import zipfile

FILES = {
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nTCAT,TCAT,https://tcat.fr/,Europe/Paris\n",
    "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type,route_color\n"
                  "R1,TCAT,1,ALPHA - ÉGLISE,3,F29400\nH,MASQUE,H,hidden,3,\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nA1,ALPHA,0,0\nB1,BETA,0,0\nB2,BETA,0,0\nE1,ÉGLISE,0,0\n",
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                    "ALL,1,1,1,1,1,1,1,20260101,20271231\n",
    "calendar_dates.txt": "service_id,date,exception_type\nALL,20261225,2\n",
    "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id\n"
                 "R1,ALL,T1,TCAT,0\nR1,ALL,T2,TCAT,0\nR1,ALL,T3,TCAT,0\nR1,ALL,T4,TCAT,1\nH,ALL,TH,TCAT,0\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                      "T1,08:00:00,08:00:00,A1,1\nT1,08:10:00,08:10:00,B1,2\nT1,08:20:00,08:20:00,E1,3\n"
                      "T2,08:30:00,08:30:00,A1,1\nT2,08:40:00,08:40:00,B1,2\nT2,08:50:00,08:50:00,E1,3\n"
                      "T3,24:30:00,24:30:00,A1,1\nT3,24:40:00,24:40:00,B1,2\nT3,24:50:00,24:50:00,E1,3\n"
                      "T4,09:00:00,09:00:00,E1,1\nT4,09:10:00,09:10:00,B2,2\nT4,09:20:00,09:20:00,A1,3\n"
                      "TH,08:00:00,08:00:00,A1,1\nTH,08:05:00,08:05:00,B1,2\n",
}


def gtfs_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in FILES.items():
            z.writestr(name, text.encode("cp1252"))  # like TCAT's export
    return buf.getvalue()


def _varint(n: int) -> bytes:
    n &= (1 << 64) - 1
    out = b""
    while True:
        out += bytes([(n & 0x7F) | (0x80 if n > 0x7F else 0)])
        n >>= 7
        if not n:
            return out


def pb(*fields) -> bytes:
    """Protobuf message from (field number, int | str | bytes) pairs."""
    out = b""
    for num, v in fields:
        if isinstance(v, int):
            out += _varint(num << 3) + _varint(v)
        else:
            v = v.encode() if isinstance(v, str) else v
            out += _varint(num << 3 | 2) + _varint(len(v)) + v
    return out


def trip_updates(*updates) -> bytes:
    """updates: (trip_id, canceled, [(seq, skipped, time or None, delay or None)])"""
    entities = []
    for trip_id, canceled, stops in updates:
        stus = [(2, pb((1, seq), (5, 1 if skipped else 0),
                       (3, pb(*([(2, t)] if t is not None else []), *([(1, d)] if d is not None else []))))) for seq, skipped, t, d in stops]
        tu = pb((1, pb((1, trip_id), (4, 3 if canceled else 0))), *stus)
        entities.append((2, pb((1, trip_id), (3, tu))))
    return pb((1, pb((1, "2.0"))), *entities)
