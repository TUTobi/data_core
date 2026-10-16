"""Simulates the Raspberry Pi: posts humidity/temperature readings to the data-core API.

    python mocks/pi_simulator.py --url http://localhost:8000 --key dev-pi-key --count 10 --interval 1
    python mocks/pi_simulator.py --backfill-hours 24      # post one reading per hour for the last 24 h
"""

import argparse
import random
import time
from datetime import UTC, datetime, timedelta

import httpx


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--key", default="dev-pi-key")
    p.add_argument("--sensor-id", default="pi-field-01")
    p.add_argument("--lat", type=float, default=-1.2921)
    p.add_argument("--lon", type=float, default=36.8219)
    p.add_argument("--count", type=int, default=5, help="live readings to send")
    p.add_argument("--interval", type=float, default=2.0, help="seconds between live readings")
    p.add_argument("--backfill-hours", type=int, default=0, help="send hourly history first")
    args = p.parse_args()

    humidity, temperature = 80.0, 22.0

    def reading(at: datetime) -> dict:
        nonlocal humidity, temperature
        humidity = min(100.0, max(30.0, humidity + random.uniform(-3, 3.5)))
        temperature = min(40.0, max(5.0, temperature + random.uniform(-0.8, 0.8)))
        return {
            "sensor_id": args.sensor_id,
            "recorded_at": at.replace(microsecond=0).isoformat(),
            "lat": args.lat,
            "lon": args.lon,
            "metrics": {"humidity_pct": round(humidity, 1), "temperature_c": round(temperature, 1)},
            "quality": "mocked",
        }

    with httpx.Client(base_url=args.url, headers={"X-API-Key": args.key}, timeout=10) as client:
        if args.backfill_hours:
            now = datetime.now(UTC)
            batch = [reading(now - timedelta(hours=h)) for h in range(args.backfill_hours, 0, -1)]
            r = client.post("/v1/sensor-readings", json={"readings": batch})
            print("backfill:", r.status_code, r.json())
        for i in range(args.count):
            r = client.post("/v1/sensor-readings", json=reading(datetime.now(UTC)))
            print(f"live {i + 1}/{args.count}:", r.status_code, r.json())
            if i + 1 < args.count:
                time.sleep(args.interval)


if __name__ == "__main__":
    main()
