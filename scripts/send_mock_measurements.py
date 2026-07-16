#!/usr/bin/env python3
"""
Feed mock DeviceMeasurement entities to Orion so the Grafana dashboard has
something to show. Only uses the Python standard library.

Usage:
    python3 scripts/send_mock_measurements.py
    python3 scripts/send_mock_measurements.py --orion-url http://localhost:1026 --points 50 --interval 0.5

Each measurement is created once, then updated `--points` times (one HTTP
call per point, `--interval` seconds apart) so QuantumLeap/CrateDB end up
with a real time series rather than a single row.

Note: the Orion subscription (k8s/orion/subscriptions-setup.yaml) only
forwards the "numValue" and "dateObserved" attributes to QuantumLeap, so
"measurementType"/"unit" are stored on the entity in Orion but will NOT show
up as columns in CrateDB/Grafana. Series in the dashboard are told apart by
entity id instead.
"""

import argparse
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

CONTEXT = "https://raw.githubusercontent.com/smart-data-models/dataModel.Device/master/context.jsonld"

MEASUREMENTS = [
    {
        "id": "urn:ngsi-ld:DeviceMeasurement:FlowRate:001",
        "measurementType": "flowRate",
        "unit": "ml/s",
        "base": 14.5,
        "amplitude": 3.0,
    },
    {
        "id": "urn:ngsi-ld:DeviceMeasurement:Temperature:001",
        "measurementType": "temperature",
        "unit": "Cel",
        "base": 22.0,
        "amplitude": 1.5,
    },
]


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def next_value(measurement, step):
    wave = measurement["amplitude"] * math.sin(step / 5.0)
    noise = random.uniform(-0.2, 0.2) * measurement["amplitude"]
    return round(measurement["base"] + wave + noise, 3)


def http_request(url, method, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/ld+json"
        },
    )
    return urllib.request.urlopen(req, timeout=10)


def create_entity(orion_url, measurement, value):
    entity = {
        "id": measurement["id"],
        "type": "DeviceMeasurement",
        "numValue": {"type": "Property", "value": value},
        "measurementType": {"type": "Property", "value": measurement["measurementType"]},
        "unit": {"type": "Property", "value": measurement["unit"]},
        "dateObserved": {"type": "Property", "value": now_iso()},
        "@context": CONTEXT,
    }
    try:
        http_request(f"{orion_url}/ngsi-ld/v1/entities", "POST", entity)
        print(f"Created {measurement['id']}")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print(f"{measurement['id']} already exists, will update it")
        else:
            raise


def update_entity(orion_url, measurement, value):
    attrs = {
        "numValue": {"type": "Property", "value": value},
        "dateObserved": {"type": "Property", "value": now_iso()},
        "@context": CONTEXT,
    }
    http_request(f"{orion_url}/ngsi-ld/v1/entities/{measurement['id']}/attrs", "POST", attrs)


def wait_for_orion(orion_url, retries=10, delay=3):
    for attempt in range(1, retries + 1):
        try:
            urllib.request.urlopen(f"{orion_url}/version", timeout=5)
            return
        except (urllib.error.URLError, urllib.error.HTTPError):
            print(f"Orion not reachable yet (attempt {attempt}/{retries}), retrying in {delay}s...")
            time.sleep(delay)
    print(f"Could not reach Orion at {orion_url} - is `minikube tunnel` running?", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--orion-url", default="http://localhost:1026", help="Orion base URL (default: %(default)s)")
    parser.add_argument("--points", type=int, default=50, help="Number of values per measurement (default: %(default)s)")
    parser.add_argument("--interval", type=float, default=0.5, help="Seconds to sleep between points (default: %(default)s)")
    args = parser.parse_args()

    wait_for_orion(args.orion_url)

    initial_values = [next_value(m, 0) for m in MEASUREMENTS]
    for measurement, value in zip(MEASUREMENTS, initial_values):
        create_entity(args.orion_url, measurement, value)

    for step in range(1, args.points):
        for measurement in MEASUREMENTS:
            value = next_value(measurement, step)
            try:
                update_entity(args.orion_url, measurement, value)
            except urllib.error.HTTPError as e:
                print(f"Failed to update {measurement['id']}: {e.code} {e.read().decode()}", file=sys.stderr)
        print(f"Sent point {step + 1}/{args.points}")
        time.sleep(args.interval)

    print("Done. Open Grafana and check the 'Device Measurements' dashboard.")


if __name__ == "__main__":
    main()
