"""Seeds DEMO caller requests so the dashboard has something to show.

Every record has channel="demo" and extra.demo=true, so the dashboard can label it as demo data.
Re-running is safe: external_ids are fixed, duplicates are returned instead of re-created.

    python mocks/seed_demo.py --url http://localhost:8000 --key dev-input-key --count 30
"""

import argparse
import random
from datetime import UTC, datetime, timedelta

import httpx

PLACES = [
    ("Nakuru", -0.3031, 36.0800),
    ("Eldoret", 0.5143, 35.2698),
    ("Kisumu", -0.0917, 34.7680),
    ("Bungoma", 0.5635, 34.5606),
    ("Kakamega", 0.2827, 34.7519),
    ("Machakos", -1.5177, 37.2634),
]
PROBLEMS = [
    ("crop_health", "maize", ["yellow leaves", "wilting"], "My maize leaves are turning yellow and wilting."),
    ("crop_health", "beans", ["brown spots"], "There are brown spots on my bean leaves."),
    ("pests", "maize", ["holes in leaves", "caterpillars"], "Caterpillars are eating holes in my maize."),
    ("pests", "potato", ["holes in tubers"], "Something is eating my potatoes in the ground."),
    ("weather_damage", "maize", ["flattened plants"], "Strong winds flattened part of my field."),
    ("soil", "beans", ["stunted growth"], "My beans are not growing, the plants stay small."),
]
REPORTED_WEATHER = ["heavy rain last week", "very dry for two weeks", "cold nights", "hot and humid", None]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--key", default="dev-input-key")
    p.add_argument("--count", type=int, default=30)
    p.add_argument("--days", type=int, default=30, help="spread calls over the last N days")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    rng = random.Random(args.seed)
    callers = [f"demo-caller-{i:02d}" for i in range(max(1, args.count * 2 // 3))]  # some call more than once
    now = datetime.now(UTC)

    with httpx.Client(base_url=args.url, headers={"X-API-Key": args.key}, timeout=60) as client:
        for i in range(args.count):
            place, lat, lon = rng.choice(PLACES)
            problem_type, crop, symptoms, text = rng.choice(PROBLEMS)
            extra = {"demo": True, "duration_s": rng.randint(45, 600)}
            if weather := rng.choice(REPORTED_WEATHER):
                extra["reported_weather"] = weather
            body = {
                "external_id": f"demo-{i:04d}",
                "channel": "demo",
                "caller_ref": rng.choice(callers),
                "received_at": (now - timedelta(minutes=rng.randint(5, args.days * 24 * 60))).isoformat(),
                "text": f"[DEMO] {text}",
                "problem_type": problem_type,
                "crop": crop,
                "symptoms": symptoms,
                "location": {
                    "lat": round(lat + rng.uniform(-0.05, 0.05), 4),
                    "lon": round(lon + rng.uniform(-0.05, 0.05), 4),
                    "name": place,
                    "precision_m": 1000,
                },
                "extra": extra,
            }
            r = client.post("/v1/requests", json=body)
            status = r.json().get("status") if r.is_success else r.text[:200]
            print(f"{i + 1}/{args.count} {body['external_id']}:", r.status_code, status)


if __name__ == "__main__":
    main()
