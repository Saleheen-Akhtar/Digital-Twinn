"""
Demo tenant data seeder for the serverless DTFM stack.

Ensures a fresh (or existing) account has a fully populated tenant:
1 building, a realistic asset roster, sensors with thresholds + current
values, recent readings, alerts, and work orders. Everything mirrors the
entity shapes in packages/types (Building/Asset/Sensor/Alert/WorkOrder).

Idempotent: if the email already has a BUILDING# item, seeding is skipped.
Call via `ensure_seeded(email)` from auth.py (first login) or from the
standalone seed CLI (aws/lambda/seed_cli.py).
"""

import boto3
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
DATA_TABLE = dynamodb.Table('dtfm-tenant-data')
READINGS_TABLE = dynamodb.Table('dtfm-sensor-readings')


def _d(v):
    """Recursively convert floats/ints to Decimal — boto3's serializer rejects plain floats."""
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, dict):
        return {k: _d(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_d(x) for x in v]
    return v

BUILDING = {
    "id": "bldg-ref-01",
    "name": "Reference Convention Centre",
    "address": "1 Exhibition Drive, Marina Bay",
    "totalFloors": 4,
    "modelUrl": None,
    "modelFormat": None,
}

# (name, type, floor, room, x, z, status)
ASSETS = [
    ("AHU-EST-01", "ahu", 1, "Plant Room Est", -8.0, 4.0, "ok"),
    ("AHU-EST-02", "ahu", 2, "Plant Room Est", -8.0, -2.0, "ok"),
    ("AHU-WST-01", "ahu", 3, "Plant Room Wst", 8.0, 4.0, "ok"),
    ("CH-BAS-01", "chiller", 1, "Plant Room Bas", 4.0, 9.0, "ok"),
    ("CH-BAS-02", "chiller", 1, "Plant Room Bas", 4.0, 9.5, "warning"),
    ("BOI-BAS-01", "boiler", 1, "Plant Room Bas", -4.0, 9.0, "ok"),
    ("PUM-CW-01", "pump", 1, "Plant Room Bas", 0.0, 8.0, "ok"),
    ("PUM-CHW-01", "pump", 1, "Plant Room Bas", 0.0, 9.0, "ok"),
    ("FAN-SUP-01", "fan", 2, "Lobby 2", -12.0, -6.0, "ok"),
    ("FAN-EXT-01", "fan", 4, "Roof Plant", 12.0, -9.0, "ok"),
    ("ELV-B01", "elevator", 1, "Lobby 1", 14.0, 0.0, "ok"),
    ("ELV-B02", "elevator", 2, "Lobby 2", 14.0, 2.0, "warning"),
    ("LTG-F1-01", "lighting", 1, "Exhibition Hall", -2.0, -8.0, "ok"),
    ("LTG-F3-01", "lighting", 3, "Ballroom", -2.0, -8.0, "ok"),
]

# (sensorId, assetId, type, unit, low, high, current, floor)
SENSORS = [
    ("s-temp-ahu1", "AHU-EST-01", "temperature", "°C", 18, 26, 22.4, 1),
    ("s-hum-ahu1", "AHU-EST-01", "humidity", "%", 30, 70, 52.0, 1),
    ("s-pwr-ahu1", "AHU-EST-01", "power", "kW", 0, 90, 34.2, 1),
    ("s-temp-ahu2", "AHU-EST-02", "temperature", "°C", 18, 26, 23.1, 2),
    ("s-hum-ahu2", "AHU-EST-02", "humidity", "%", 30, 70, 48.0, 2),
    ("s-pwr-ahu2", "AHU-EST-02", "power", "kW", 0, 90, 29.8, 2),
    ("s-temp-ch1", "CH-BAS-01", "temperature", "°C", 5, 12, 7.2, 1),
    ("s-pwr-ch1", "CH-BAS-01", "power", "kW", 0, 250, 118.0, 1),
    ("s-flow-ch1", "CH-BAS-01", "flow", "m³/h", 0, 160, 88.4, 1),
    ("s-temp-ch2", "CH-BAS-02", "temperature", "°C", 5, 12, 11.6, 1),
    ("s-pwr-ch2", "CH-BAS-02", "power", "kW", 0, 250, 143.5, 1),
    ("s-temp-boi", "BOI-BAS-01", "temperature", "°C", 60, 95, 78.2, 1),
    ("s-pwr-boi", "BOI-BAS-01", "power", "kW", 0, 400, 196.0, 1),
    ("s-pwr-pum1", "PUM-CW-01", "power", "kW", 0, 45, 18.7, 1),
    ("s-flow-pum1", "PUM-CW-01", "flow", "m³/h", 0, 120, 64.0, 1),
    ("s-pwr-pum2", "PUM-CHW-01", "power", "kW", 0, 45, 21.3, 1),
    ("s-flow-pum2", "PUM-CHW-01", "flow", "m³/h", 0, 120, 71.2, 1),
    ("s-temp-lobby2", "FAN-SUP-01", "temperature", "°C", 18, 26, 24.8, 2),
    ("s-co2-lobby2", "FAN-SUP-01", "co2", "ppm", 0, 1000, 620.0, 2),
    ("s-occ-lobby2", "FAN-SUP-01", "occupancy", "ppl", 0, 200, 84.0, 2),
    ("s-pwr-fan1", "FAN-SUP-01", "power", "kW", 0, 30, 11.4, 2),
    ("s-temp-roof", "FAN-EXT-01", "temperature", "°C", 18, 30, 27.6, 4),
    ("s-pwr-fan2", "FAN-EXT-01", "power", "kW", 0, 30, 9.1, 4),
    ("s-occ-lift1", "ELV-B01", "occupancy", "ppl", 0, 16, 6.0, 1),
    ("s-pwr-lift1", "ELV-B01", "power", "kW", 0, 40, 12.6, 1),
    ("s-occ-lift2", "ELV-B02", "occupancy", "ppl", 0, 16, 14.0, 2),
    ("s-temp-hall", "LTG-F1-01", "temperature", "°C", 18, 26, 25.3, 1),
    ("s-co2-hall", "LTG-F1-01", "co2", "ppm", 0, 1000, 780.0, 1),
    ("s-occ-hall", "LTG-F1-01", "occupancy", "ppl", 0, 500, 232.0, 1),
    ("s-pwr-ltg1", "LTG-F1-01", "power", "kW", 0, 60, 24.0, 1),
]

ALERTS = [
    ("CH-BAS-02", "chiller_fault_ch2", "high", "open",
     "Chiller 2 return temperature above threshold — check condenser fouling", 1),
    ("ELV-B02", "lift2_heavy_use", "medium", "acknowledged",
     "Lift B2 occupancy near capacity during peak hours", 2),
    ("AHU-EST-01", "ahu1_filter", "low", "resolved",
     "AHU-1 supply filter differential pressure above baseline", 1),
    ("FAN-EXT-01", "roof_fan_temp", "medium", "open",
     "Roof exhaust fan ambient temperature elevated", 4),
    ("CH-BAS-01", "chiller1_pm_due", "low", "resolved",
     "Chiller 1 preventive maintenance due", 1),
    ("BOI-BAS-01", "boiler1_hot", "high", "open",
     "Boiler 1 supply temperature approaching upper bound", 1),
]

WORK_ORDERS = [
    ("CH-BAS-02", "chiller_fault_ch2", "Preventive overhaul Chiller 2", "preventive",
     "high", "in_progress", "Roger Tan", 2),
    ("AHU-EST-01", "ahu1_filter", "Replace AHU-1 supply air filter", "corrective",
     "medium", "open", "Mei Lin", 2),
    ("FAN-EXT-01", "roof_fan_temp", "Inspect roof fan motor bearings", "predictive",
     "medium", "open", "Arif Rahman", 4),
    ("ELV-B01", None, "Lift B1 statutory inspection", "inspection",
     "low", "completed", "Suresh Kumar", 1),
    ("PUM-CW-01", None, "CW pump seal replacement", "corrective",
     "medium", "completed", "Roger Tan", 1),
]

NOTIF_SENSOR = "s-temp-lobby2"

# alert id → real sensor id (so alerts link to existing sensors)
NEXT = {
    "chiller_fault_ch2": "s-temp-ch2",
    "lift2_heavy_use": "s-occ-lift2",
    "ahu1_filter": "s-temp-ahu1",
    "roof_fan_temp": "s-temp-roof",
    "chiller1_pm_due": "s-temp-ch1",
    "boiler1_hot": "s-temp-boi",
}


def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def tenant_exists(email):
    """True only when the tenant has real data (assets), not just the BUILDING
    sentinel. A sentinel-only tenant means a previous seed attempt failed
    partway (e.g. the float bug) — that must be re-seeded on next login."""
    res = DATA_TABLE.query(
        KeyConditionExpression="email = :e AND begins_with(sk, :p)",
        ExpressionAttributeValues={":e": email, ":p": "ASSET#"},
        Select="COUNT",
        Limit=1,
    )
    return bool(res.get("Count"))


def flush(table, items):
    """Push items via batch_write_item (25/chunk, auto-retried) — fast enough to fit the 30s lambda timeout."""
    if not items:
        return
    with table.batch_writer() as writer:
        for item in items:
            writer.put_item(Item=item)


def seed_tenant(email):
    """Write the demo dataset for `email`. Idempotent per tenant.

    Writes the BUILDING sentinel LAST: if the batch writes fail partway
    (e.g. lambda timeout), the next login retries instead of thinking the
    tenant exists. All writes use batch_write_item to stay well under the
    auth lambda's 30s timeout.
    """
    if tenant_exists(email):
        return False

    ts = now_iso()
    prev_hour = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"

    data_items = []

    # Assets
    for (name, atype, floor, room, x, z, status) in ASSETS:
        data_items.append(_d({
            "email": email, "sk": f"ASSET#{name}",
            "id": name,
            "buildingId": BUILDING["id"],
            "floorId": f"floor-{floor}",
            "roomId": f"room-{floor}-{room.lower().replace(' ', '-')}",
            "name": name,
            "type": atype,
            "status": status,
            "manufacturer": "Johnson Controls" if atype in ("ahu", "chiller") else "Grundfos" if atype == "pump" else "Schneider Electric",
            "model": f"{atype.upper()}-{floor}",
            "serialNumber": f"SN-{name}",
            "installedAt": "2024-03-15T09:00:00Z",
            "positionX": x,
            "positionY": float(floor) * 3.2,
            "positionZ": z,
            "floorLevel": floor,
            "floorName": f"Level {floor}",
            "roomName": room,
            "createdAt": ts, "updatedAt": ts,
        }))

    # Sensors (lastValue matches running values so charts render immediately)
    for (sid, asset, stype, unit, low, high, value, floor) in SENSORS:
        near_high = value > high - 1 if high else False
        data_items.append(_d({
            "email": email, "sk": f"SENSOR#{sid}",
            "id": sid,
            "assetId": asset,
            "buildingId": BUILDING["id"],
            "type": stype,
            "unit": unit,
            "status": "warning" if near_high else "ok",
            "thresholdLow": low,
            "thresholdHigh": high,
            "lastValue": Decimal(str(value)),
            "lastReadingAt": prev_hour,
            "floorLevel": floor,
            "createdAt": ts,
        }))

    # Alerts
    for (asset, aid, severity, status, message, floor) in ALERTS:
        ack_at = ts if status == "acknowledged" else None
        data_items.append(_d({
            "email": email, "sk": f"ALERT#{aid}",
            "id": aid,
            "assetId": asset,
            "sensorId": NEXT[aid] if aid in NEXT else None,
            "severity": severity,
            "status": status,
            "message": message,
            "acknowledgedBy": "system" if status in ("acknowledged", "resolved") else None,
            "acknowledgedAt": (datetime.utcnow() - timedelta(hours=6)).isoformat() + "Z" if ack_at else None,
            "resolvedAt": (datetime.utcnow() - timedelta(hours=4)).isoformat() + "Z" if status == "resolved" else None,
            "createdAt": (datetime.utcnow() - timedelta(hours=7)).isoformat() + "Z",
        }))

    # Work orders
    for (asset, alert_id, title, wtype, priority, status, assignee, floor) in WORK_ORDERS:
        data_items.append(_d({
            "email": email, "sk": f"WORKORDER#{str(uuid.uuid4())[:8]}",
            "id": str(uuid.uuid4())[:8],
            "assetId": asset,
            "alertId": alert_id,
            "title": title,
            "description": title,
            "type": wtype,
            "priority": priority,
            "status": status,
            "assignedTo": assignee,
            "createdBy": "facility_manager",
            "startedAt": (datetime.utcnow() - timedelta(hours=5)).isoformat() + "Z" if status == "in_progress" else None,
            "completedAt": (datetime.utcnow() - timedelta(hours=3)).isoformat() + "Z" if status == "completed" else None,
            "dueAt": (datetime.utcnow() + timedelta(days=2)).isoformat() + "Z",
            "createdAt": (datetime.utcnow() - timedelta(hours=8)).isoformat() + "Z",
            "updatedAt": (datetime.utcnow() - timedelta(hours=3)).isoformat() + "Z",
        }))

    # All tenant data in a few batched writes (fast, fits the 30s timeout)
    flush(DATA_TABLE, data_items)

    # Sensor readings: ~45 points per sensor over the last hour
    reading_items = []
    for (sid, _asset, _stype, unit, _low, _high, base, _floor) in SENSORS:
        start = datetime.utcnow() - timedelta(hours=1)
        for i in range(45):
            t = start + timedelta(minutes=i)
            jitter = (i % 7 - 3) * 0.35
            val = base + jitter
            reading_items.append(_d({
                "email": email,
                "timestamp": t.isoformat() + "Z",
                "sensorId": sid,
                "value": round(val, 2),
                "unit": unit,
                "quality": "good",
            }))
    flush(READINGS_TABLE, reading_items)

    # Building sentinel LAST: if anything above failed partway, the next
    # login retries the seed instead of thinking the tenant exists.
    DATA_TABLE.put_item(Item=_d({
        "email": email, "sk": f"BUILDING#{BUILDING['id']}",
        **BUILDING, "createdAt": ts, "updatedAt": ts,
    }))

    return True


def ensure_seeded(email):
    """Called on login — populates the tenant if missing. Returns True if seeded."""
    return seed_tenant(email)


if __name__ == "__main__":
    import sys
    email = sys.argv[1] if len(sys.argv) > 1 else "saleheenakhtar.56@gmail.com"
    seeded = seed_tenant(email)
    print(f"tenant={email} seeded={seeded}")