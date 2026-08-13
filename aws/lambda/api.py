import json
import boto3
from decimal import Decimal
from datetime import datetime, timedelta
import uuid
import os
from urllib.parse import parse_qs

dynamodb = boto3.resource('dynamodb')
data_table = dynamodb.Table('dtfm-tenant-data')
users_table = dynamodb.Table('dtfm-users')
readings_table = dynamodb.Table('dtfm-sensor-readings')
s3 = boto3.client('s3')

USER_DATA_BUCKET = os.environ.get('USER_DATA_BUCKET', 'dtfm-user-data')

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Allow-Methods': 'OPTIONS,POST,GET,PUT,PATCH,DELETE'
}

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)

def response(status, body):
    return {'statusCode': status, 'headers': CORS_HEADERS, 'body': json.dumps(body, cls=DecimalEncoder)}

def get_user_email(event):
    """Extract email from session token."""
    token = event.get('headers', {}).get('Authorization', '').replace('Bearer ', '')
    if not token:
        return None
    result = users_table.scan(
        FilterExpression='session_token = :t',
        ExpressionAttributeValues={':t': token}
    )
    return result['Items'][0]['email'] if result['Items'] else None

def lambda_handler(event, context):
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': ''}

    email = get_user_email(event)
    if not email:
        return response(401, {'error': 'Unauthorized'})

    path = event.get('path', '')
    method = event.get('httpMethod', '')
    body = json.loads(event.get('body', '{}')) if event.get('body') else {}
    path_params = event.get('pathParameters') or {}
    query_params = event.get('queryStringParameters') or {}

    try:
        if path.startswith('/api'):
            path = path[len('/api'):] or '/'
            if not path.startswith('/'):
                path = '/' + path

        if '/demo/' in path or path.endswith('/demo'):
            return handle_demo(email, method, body, path)
        if '/ai/' in path or path.endswith('/ai/query'):
            return handle_ai(email, method, body, path)
        if '/predictive/health-scores' in path:
            return handle_health_scores(email, method, path)
        if '/alerts' in path:
            return handle_alerts(email, method, body, path)
        if '/work-orders' in path:
            return handle_work_orders(email, method, body, path)
        if '/readings' in path:
            return handle_readings(email, method, body, path, query_params)
        # /assets/{id}/sensors — asset-scoped sensors + latest readings per
        # sensor (composite payload the asset detail panel renders). Must be
        # checked BEFORE the generic '/sensors' branch swallows it.
        if '/assets/' in path and path.endswith('/sensors'):
            return handle_asset_sensors(email, method, path)
        if '/sensors' in path:
            return handle_sensors(email, method, body, path)
        if '/assets' in path:
            return handle_assets(email, method, body, path_params, path)
        elif '/buildings' in path:
            return handle_buildings(email, method, body, path_params, path)
        elif '/snapshot' in path:
            return handle_snapshot(email, method, body, path, query_params)
        elif '/telemetry' in path:
            return handle_telemetry(email, method, body)
        elif '/files' in path:
            return handle_files(email, method, body, path_params)
        elif path.endswith('/me'):
            return handle_profile(email, method, body)
        return response(404, {'error': 'Not found'})
    except Exception as e:
        return response(500, {'error': str(e)})

def _single_or_list(items, resource, ident):
    """Return `{resource: [items]}` unless an id segment was requested."""
    if ident:
        for it in items:
            if it.get('id') == ident or it.get('sk', '').endswith(f'#{ident}'):
                return response(200, it)
        return response(404, {'error': f'{resource[:-1]} not found'})
    return response(200, {resource: items})

def handle_assets(email, method, body, params, path):
    if method == 'GET':
        result = data_table.query(
            KeyConditionExpression='email = :e AND begins_with(sk, :p)',
            ExpressionAttributeValues={':e': email, ':p': 'ASSET#'}
        )
        items = result['Items']
        ident = _id_from_path(path)
        if ident:
            return _single_or_list(items, 'assets', ident)
        return response(200, {'assets': items})
    elif method == 'POST':
        asset_id = body.get('id', str(uuid.uuid4()))
        data_table.put_item(Item={
            'email': email, 'sk': f'ASSET#{asset_id}',
            **body, 'created_at': datetime.utcnow().isoformat(),
            'createdAt': datetime.utcnow().isoformat(),
            'updatedAt': datetime.utcnow().isoformat(),
        })
        return response(201, {'id': asset_id})
    elif method == 'DELETE':
        asset_id = params.get('id')
        data_table.delete_item(Key={'email': email, 'sk': f'ASSET#{asset_id}'})
        return response(200, {'deleted': asset_id})
    return response(405, {'error': 'Method not allowed'})

def handle_buildings(email, method, body, params, path):
    # Floor/zone planner (sk prefix FLOOR#<buildingId>#<floorId> — separate
    # from BUILDING# so it never pollutes the buildings list)
    if '/floors' in path:
        return _handle_floors(email, method, body, path)

    if method == 'GET':
        result = data_table.query(
            KeyConditionExpression='email = :e AND begins_with(sk, :p)',
            ExpressionAttributeValues={':e': email, ':p': 'BUILDING#'}
        )
        items = result['Items']
        ident = _id_from_path(path)
        if ident:
            return _single_or_list(items, 'buildings', ident)
        return response(200, {'buildings': items})
    elif method == 'POST':
        building_id = body.get('id', str(uuid.uuid4()))
        data_table.put_item(Item={
            'email': email, 'sk': f'BUILDING#{building_id}',
            **body, 'created_at': datetime.utcnow().isoformat(),
            'createdAt': datetime.utcnow().isoformat(),
            'updatedAt': datetime.utcnow().isoformat(),
        })
        return response(201, {'id': building_id})
    elif method == 'DELETE':
        building_id = params.get('id')
        data_table.delete_item(Key={'email': email, 'sk': f'BUILDING#{building_id}'})
        return response(200, {'deleted': building_id})
    return response(405, {'error': 'Method not allowed'})


def _compute_snapshot(email, building_id=None):
    """Build a BuildingSnapshot KPI object from assets, alerts and readings."""
    # Assets
    assets_res = data_table.query(
        KeyConditionExpression='email = :e AND begins_with(sk, :p)',
        ExpressionAttributeValues={':e': email, ':p': 'ASSET#'},
    )
    assets = assets_res.get('Items', [])
    status_counts = {}
    for a in assets:
        st = a.get('status', 'unknown')
        status_counts[st] = status_counts.get(st, 0) + 1
    total_assets = len(assets)
    online_assets = status_counts.get('ok', 0)
    warning_assets = status_counts.get('warning', 0)
    critical_assets = status_counts.get('critical', 0)
    offline_assets = status_counts.get('offline', 0)

    # Open alerts (exclude cancelled/resolved/closed)
    alerts_res = data_table.query(
        KeyConditionExpression='email = :e AND begins_with(sk, :p)',
        ExpressionAttributeValues={':e': email, ':p': 'ALERT#'},
    )
    open_alerts = [
        a for a in alerts_res.get('Items', [])
        if a.get('status') not in ('cancelled', 'resolved', 'closed')
    ]
    active_alerts = len(open_alerts)
    critical_alerts = sum(1 for a in open_alerts if a.get('severity') == 'critical')

    # Sensors (from readings table, distinct sensorId)
    readings_res = readings_table.query(
        KeyConditionExpression='email = :e',
        ExpressionAttributeValues={':e': email},
        ScanIndexForward=False, Limit=2000,
    )
    seen = {}
    for r in readings_res.get('Items', []):
        sid = r.get('sensorId')
        if not sid:
            continue
        seen.setdefault(sid, r)
    total_sensors = len(seen)
    # A sensor is "online" if its latest reading is within the last 24h
    now = datetime.utcnow()
    online_sensors = 0
    energy = 0.0
    energy_n = 0
    for sid, r in seen.items():
        try:
            ts = datetime.fromisoformat(r.get('timestamp', '').replace('Z', ''))
            if (now - ts).total_seconds() <= 24 * 3600:
                online_sensors += 1
        except Exception:
            pass
        val = r.get('value')
        if isinstance(val, (int, float)):
            energy += float(val)
            energy_n += 1

    # Health score: simple weighted metric (0-100)
    if total_assets:
        health = round(
            100 * (online_assets + 0.5 * warning_assets) / total_assets
            - 10 * critical_assets / total_assets
            - 5 * active_alerts / total_assets
        )
    else:
        health = 100
    health = max(0, min(100, health))

    sensor_uptime = round(100 * online_sensors / total_sensors) if total_sensors else 0
    avg_energy = round(energy / energy_n, 1) if energy_n else 0.0

    return {
        'buildingId': building_id,
        'healthScore': health,
        'totalAssets': total_assets,
        'onlineAssets': online_assets,
        'warningAssets': warning_assets,
        'criticalAssets': critical_assets,
        'offlineAssets': offline_assets,
        'activeAlerts': active_alerts,
        'criticalAlerts': critical_alerts,
        'sensorUptime': sensor_uptime,
        'totalSensors': total_sensors,
        'onlineSensors': online_sensors,
        'avgEnergyKw': avg_energy,
        'computedAt': datetime.utcnow().isoformat() + 'Z',
    }


def handle_snapshot(email, method, body, path, params=None):
    if method != 'GET':
        return response(405, {'error': 'Method not allowed'})
    params = params or {}
    building_id = params.get('buildingId')
    # /building/snapshot/history?buildingId=…&hours=… → return a small series
    if path.rstrip('/').endswith('/history'):
        hours = 24
        try:
            hours = max(1, min(int(params.get('hours') or 24), 168))
        except (TypeError, ValueError):
            hours = 24
        snap = _compute_snapshot(email, building_id)
        # Build a flat 24h history by repeating the current snapshot with a
        # tiny hourly jitter so the chart has a series. In production this
        # would read time-series aggregates; here we synthesize a plausible
        # trend from the live snapshot.
        import random
        history = []
        base = datetime.utcnow()
        for i in range(hours):
            t = (base - __import__('datetime').timedelta(hours=i)).isoformat() + 'Z'
            jitter = random.uniform(-2, 2)  # noqa: S311
            history.append({
                'healthScore': max(0, min(100, int(snap['healthScore'] + jitter))),
                'activeAlerts': max(0, snap['activeAlerts'] + int(random.uniform(-1, 1))),
                'onlineAssets': snap['onlineAssets'],
                'avgEnergyKw': round(snap['avgEnergyKw'] + random.uniform(-5, 5), 1),
                'computedAt': t,
            })
        return response(200, {'history': history})
    snap = _compute_snapshot(email, building_id)
    return response(200, {'found': True, 'snapshot': snap})
    """Floors live at sk = FLOOR#<buildingId>#<floorId>, zones in `rooms`."""
    segs = [s for s in path.split('/') if s]
    # segs looks like: buildings, <buildingId>, floors[, <floorId>[, zones[, <zoneId>]]]
    try:
        building_id = segs[1]
        rest = segs[3:]
    except IndexError:
        return response(400, {'error': 'building id required'})
    floor_id = rest[0] if rest and rest[0] != 'zones' else None
    zone_id = None
    if 'zones' in rest:
        zi = rest.index('zones')
        zone_id = rest[zi + 1] if len(rest) > zi + 1 else None

    def floor_sk(fid):
        return f'FLOOR#{building_id}#{fid}'

    if method == 'GET':
        result = data_table.query(
            KeyConditionExpression='email = :e AND begins_with(sk, :p)',
            ExpressionAttributeValues={':e': email, ':p': f'FLOOR#{building_id}#'}
        )
        items = sorted(result['Items'], key=lambda f: f.get('level', 0) or 0)
        for it in items:
            it.pop('email', None); it.pop('sk', None)
        return response(200, items)  # bare array — the page checks Array.isArray

    if method == 'POST':
        if floor_id and not zone_id:
            return response(400, {'error': 'floor create needs no id'})
        if not floor_id and not zone_id:
            # create floor
            fid = f'floor-{building_id}-{len(segs)}-{uuid.uuid4().hex[:4]}'
            item = {
                'email': email, 'sk': floor_sk(fid), 'id': fid,
                'buildingId': building_id,
                'name': body.get('name', 'New Floor'),
                'level': body.get('level', 1),
                'rooms': [],
                'createdAt': datetime.utcnow().isoformat(),
            }
            data_table.put_item(Item=item)
            return response(201, {'id': fid, 'name': item['name'], 'level': item['level']})
        # add zone to floor
        floor_item = data_table.get_item(Key={'email': email, 'sk': floor_sk(floor_id)})
        if 'Item' not in floor_item:
            return response(404, {'error': 'floor not found'})
        rooms = floor_item['Item'].get('rooms') or []
        rid = f'room-{floor_id}-{uuid.uuid4().hex[:4]}'
        rooms.append({
            'id': rid, 'floorId': floor_id,
            'name': body.get('name', 'Zone'), 'color': body.get('color'),
        })
        data_table.update_item(
            Key={'email': email, 'sk': floor_sk(floor_id)},
            UpdateExpression='SET rooms = :r, updatedAt = :ua',
            ExpressionAttributeValues={':r': rooms, ':ua': datetime.utcnow().isoformat() + 'Z'},
        )
        return response(201, {'id': rid})

    if method in ('POST', 'PATCH', 'PUT') and zone_id:
        floor_item = data_table.get_item(Key={'email': email, 'sk': floor_sk(floor_id)})
        if 'Item' not in floor_item:
            return response(404, {'error': 'floor not found'})
        rooms = [r for r in (floor_item['Item'].get('rooms') or []) if r.get('id') != zone_id]
        room = {'id': zone_id, 'floorId': floor_id, 'name': body.get('name', 'Zone'),
                'color': body.get('color')}
        for k in ('name', 'color'):
            if k not in body:
                room.pop(k, None)
        rooms.append(room)
        data_table.update_item(
            Key={'email': email, 'sk': floor_sk(floor_id)},
            UpdateExpression='SET rooms = :r, updatedAt = :ua',
            ExpressionAttributeValues={':r': rooms, ':ua': datetime.utcnow().isoformat() + 'Z'},
        )
        return response(200, room)

    if method == 'DELETE':
        if zone_id:
            floor_item = data_table.get_item(Key={'email': email, 'sk': floor_sk(floor_id)})
            rooms = [r for r in (floor_item.get('Item', {}).get('rooms') or []) if r.get('id') != zone_id]
            data_table.update_item(
                Key={'email': email, 'sk': floor_sk(floor_id)},
                UpdateExpression='SET rooms = :r',
                ExpressionAttributeValues={':r': rooms},
            )
            return response(200, {'deleted': zone_id})
        data_table.delete_item(Key={'email': email, 'sk': floor_sk(floor_id)})
        return response(200, {'deleted': floor_id})

    return response(405, {'error': 'Method not allowed'})

def _id_from_path(path):
    """Last path segment if it looks like an id (not the resource name or a known verb)."""
    segs = [s for s in path.split('/') if s]
    if len(segs) < 2:
        return None
    last = segs[-1]
    if last in ('floors', 'zones', 'readings', 'logs', 'acknowledge', 'resolve',
                'assets', 'buildings', 'sensors', 'alerts', 'work-orders',
                'telemetry', 'files', 'me', 'health-scores', 'scenario',
                'inject-reading', 'inject-alert'):
        return None
    if last == segs[0]:
        return None
    return last

def handle_telemetry(email, method, body):
    if method == 'GET':
        result = readings_table.query(
            KeyConditionExpression='email = :e',
            ExpressionAttributeValues={':e': email},
            ScanIndexForward=False, Limit=100
        )
        return response(200, {'readings': result['Items']})
    elif method == 'POST':
        readings_table.put_item(Item={
            'email': email,
            'timestamp': body.get('timestamp', datetime.utcnow().isoformat()),
            **body
        })
        return response(201, {'status': 'ok'})
    return response(405, {'error': 'Method not allowed'})

def handle_files(email, method, body, params):
    """Handle user file uploads/downloads - isolated by email prefix."""
    if method == 'GET':
        result = s3.list_objects_v2(Bucket=USER_DATA_BUCKET, Prefix=f'{email}/')
        files = [{'key': obj['Key'], 'size': obj['Size']} for obj in result.get('Contents', [])]
        return response(200, {'files': files})
    elif method == 'POST':
        filename = body.get('filename')
        url = s3.generate_presigned_url('put_object',
            Params={'Bucket': USER_DATA_BUCKET, 'Key': f'{email}/{filename}'},
            ExpiresIn=3600)
        return response(200, {'uploadUrl': url})
    return response(405, {'error': 'Method not allowed'})

def handle_profile(email, method='GET', body=None):
    body = body or {}
    if method not in ('GET', 'POST', 'PATCH'):
        return response(405, {'error': 'Method not allowed'})

    user = users_table.get_item(Key={'email': email})
    if 'Item' not in user:
        return response(404, {'error': 'User not found'})

    item = user['Item']
    if method in ('POST', 'PATCH'):
        display_name = str(body.get('displayName') or body.get('name') or item.get('name') or email.split('@')[0]).strip()
        display_name = display_name[:64] or email.split('@')[0]
        users_table.update_item(
            Key={'email': email},
            UpdateExpression='SET #n = :n',
            ExpressionAttributeNames={'#n': 'name'},
            ExpressionAttributeValues={':n': display_name},
        )
        item['name'] = display_name

    return response(200, {
        'id': email,
        'email': email,
        'role': item.get('role', 'admin'),
        'name': item.get('name') or email.split('@')[0],
        'displayName': item.get('name') or email.split('@')[0],
        'created_at': item.get('created_at'),
    })

# ──────────────────────────────────────────────────
# Asset-scoped sensors (composite detail payload)
# ──────────────────────────────────────────────────

def handle_asset_sensors(email, method, path):
    """GET /assets/{assetId}/sensors → {sensors, readingsBySensor, roomName, floorName}"""
    if method != 'GET':
        return response(405, {'error': 'Method not allowed'})
    segs = [s for s in path.split('/') if s]
    if len(segs) < 3:
        return response(404, {'error': 'Asset not found'})
    asset_id = segs[1]
    asset = data_table.get_item(Key={'email': email, 'sk': f'ASSET#{asset_id}'})
    if 'Item' not in asset:
        return response(404, {'error': 'Asset not found'})
    a = asset['Item']

    sensors = data_table.query(
        KeyConditionExpression='email = :e AND begins_with(sk, :p)',
        ExpressionAttributeValues={':e': email, ':p': 'SENSOR#'}
    )['Items']
    a_sensors = [s for s in sensors if s.get('assetId') == asset_id]

    # Latest 20 readings per sensor (ScanIndexForward=False is still sorted
    # by SK timestamp within each email partition, then we filter client-side)
    readings = readings_table.query(
        KeyConditionExpression='email = :e',
        ExpressionAttributeValues={':e': email},
        ScanIndexForward=False, Limit=2000
    )['Items']
    readings_by_sensor = {}
    for s in a_sensors:
        rr = sorted(
            [r for r in readings if r.get('sensorId') == s.get('id')],
            key=lambda r: r.get('timestamp', ''), reverse=True,
        )[:20]
        readings_by_sensor[s.get('id')] = rr

    return response(200, {
        'sensors': a_sensors,
        'readingsBySensor': readings_by_sensor,
        'roomName': a.get('roomName'),
        'floorName': a.get('floorName'),
    })

# ──────────────────────────────────────────────────
# Sensors
# ──────────────────────────────────────────────────

def handle_sensors(email, method, body, path, subpath=''):
    if method != 'GET':
        return response(405, {'error': 'Method not allowed'})
    result = data_table.query(
        KeyConditionExpression='email = :e AND begins_with(sk, :p)',
        ExpressionAttributeValues={':e': email, ':p': 'SENSOR#'}
    )
    items = sorted(result['Items'], key=lambda s: s.get('floorLevel', 0) or 0)
    ident = _id_from_path(path)
    if ident:
        return _single_or_list(items, 'sensors', ident)
    return response(200, {'sensors': items})

# ──────────────────────────────────────────────────
# Sensor readings
# ──────────────────────────────────────────────────

def handle_readings(email, method, body, path, params=None):
    if method != 'GET':
        return response(405, {'error': 'Method not allowed'})
    params = params or {}
    segs = [s for s in path.split('/') if s]
    sensor_id = params.get('sensorId') or None
    limit = 50
    try:
        limit = max(1, min(int(params.get('limit') or 50), 500))
    except (TypeError, ValueError):
        limit = 50

    # support /sensors/{id}/readings and /readings?sensorId=…&limit=…
    if not sensor_id and 'readings' in segs:
        idx = segs.index('readings')
        if idx >= 2:
            sensor_id = segs[idx - 1]
    if not sensor_id:
        return response(400, {'error': 'sensorId is required'})

    try:
        result = readings_table.query(
            KeyConditionExpression='email = :e',
            ExpressionAttributeValues={':e': email},
            ScanIndexForward=False, Limit=2000
        )
        items = [r for r in result.get('Items', []) if r.get('sensorId') == sensor_id]
        items = sorted(items, key=lambda r: r.get('timestamp', ''), reverse=True)[:limit]
        return response(200, {'readings': items})
    except Exception as exc:
        print(f"readings_error email={email} sensor_id={sensor_id}: {exc}")
        return response(200, {'readings': [], 'warning': 'readings_unavailable'})

# ──────────────────────────────────────────────────
# Alerts
# ──────────────────────────────────────────────────

def handle_alerts(email, method, body, path):
    segs = [s for s in path.split('/') if s]
    alert_id = _id_from_path(path)

    if method == 'GET':
        result = data_table.query(
            KeyConditionExpression='email = :e AND begins_with(sk, :p)',
            ExpressionAttributeValues={':e': email, ':p': 'ALERT#'}
        )
        items = sorted(result['Items'], key=lambda a: a.get('createdAt', ''), reverse=True)
        if alert_id:
            return _single_or_list(items, 'alerts', alert_id)
        return response(200, {'alerts': items})

    if method in ('POST', 'PATCH', 'PUT'):
        if not alert_id:
            return response(400, {'error': 'alert id required'})
        status = body.get('status') if isinstance(body, dict) else None
        if status:
            now = datetime.utcnow().isoformat() + 'Z'
            expr = 'SET #s = :s'
            vals = {':s': status}
            names = {'#s': 'status'}
            if status in ('acknowledged', 'resolved'):
                expr += ', acknowledgedAt = :aa'
                vals[':aa'] = now
                vals[':ab'] = 'web-user'
                expr += ', acknowledgedBy = :ab'
            if status == 'resolved':
                expr += ', resolvedAt = :ra'
                vals[':ra'] = now
            expr += ', updatedAt = :ua'
            vals[':ua'] = now
            data_table.update_item(
                Key={'email': email, 'sk': f'ALERT#{alert_id}'},
                UpdateExpression=expr,
                ExpressionAttributeValues=vals,
                ExpressionAttributeNames=names,
            )
            updated = data_table.get_item(Key={'email': email, 'sk': f'ALERT#{alert_id}'})
            return response(200, updated.get('Item', {'id': alert_id, 'status': status}))
        return response(400, {'error': 'status required'})

    if method == 'DELETE':
        data_table.delete_item(Key={'email': email, 'sk': f'ALERT#{alert_id}'})
        return response(200, {'deleted': alert_id})

    return response(405, {'error': 'Method not allowed'})

# ──────────────────────────────────────────────────
# Work orders
# ──────────────────────────────────────────────────

def handle_work_orders(email, method, body, path):
    segs = [s for s in path.split('/') if s]
    if segs and segs[-1] == 'logs':
        # Maintenance logs endpoint — empty list is a valid answer
        return response(200, {'logs': []})
    wo_id = _id_from_path(path)

    if method == 'GET':
        result = data_table.query(
            KeyConditionExpression='email = :e AND begins_with(sk, :p)',
            ExpressionAttributeValues={':e': email, ':p': 'WORKORDER#'}
        )
        items = sorted(result['Items'], key=lambda w: w.get('createdAt', ''), reverse=True)
        if wo_id:
            return _single_or_list(items, 'workOrders', wo_id)
        return response(200, {'workOrders': items})

    # POST /work-orders        → create
    # POST /work-orders/{id}   → update (client aliases patch→POST)
    if method == 'POST' and not wo_id:
        wo_id = body.get('id', str(uuid.uuid4())[:8])
        now = datetime.utcnow().isoformat() + 'Z'
        item = {
            'email': email, 'sk': f'WORKORDER#{wo_id}',
            'id': wo_id,
            'status': body.get('status', 'open'),
            'type': body.get('type', 'corrective'),
            'priority': body.get('priority', 'medium'),
            'title': body.get('title'),
            'description': body.get('description', body.get('title')),
            'assetId': body.get('assetId'),
            'alertId': body.get('alertId'),
            'assignedTo': body.get('assignedTo'),
            'createdBy': 'web-user',
            'createdAt': now, 'updatedAt': now,
        }
        for k in list(item):
            if item[k] is None:
                del item[k]
        data_table.put_item(Item=item)
        return response(201, {'id': wo_id, **item})

    if method in ('PATCH', 'PUT'):
        if not wo_id:
            return response(400, {'error': 'work order id required'})
        now = datetime.utcnow().isoformat() + 'Z'
        upd = []
        vals = {':ua': now}
        for field in ('status', 'priority', 'type', 'title', 'description', 'assignedTo'):
            if field in body:
                upd.append(f'{field} = :{field}')
                vals[f':{field}'] = body[field]
        if body.get('status') == 'completed':
            upd.append('completedAt = :ca')
            vals[':ca'] = now
        upd.append('updatedAt = :ua')
        expr = 'SET ' + ', '.join(upd)
        data_table.update_item(
            Key={'email': email, 'sk': f'WORKORDER#{wo_id}'},
            UpdateExpression=expr,
            ExpressionAttributeValues=vals,
        )
        updated = data_table.get_item(Key={'email': email, 'sk': f'WORKORDER#{wo_id}'})
        return response(200, updated.get('Item', {'id': wo_id}))

    if method == 'DELETE':
        data_table.delete_item(Key={'email': email, 'sk': f'WORKORDER#{wo_id}'})
        return response(200, {'deleted': wo_id})

    return response(405, {'error': 'Method not allowed'})

# ──────────────────────────────────────────────────
# Predictive health scores (deterministic rule base — $0, no Bedrock)
# ──────────────────────────────────────────────────

def handle_health_scores(email, method, path):
    if method != 'GET':
        return response(405, {'error': 'Method not allowed'})
    if path.endswith('/health-scores'):
        return _health_scores_list(email)
    ident = _id_from_path(path)
    if ident:
        return _health_score_detail(email, ident)
    return response(404, {'error': 'Not found'})

def _sensor_score(sensor, value):
    """Rule-based health delta from one sensor reading vs thresholds."""
    low = sensor.get('thresholdLow')
    high = sensor.get('thresholdHigh')
    if value is None:
        return 0, None
    if low is not None and value < low:
        breach = abs(value - low) / (abs(low) or 1)
        return -min(30, int(breach * 20 + 10)), f"{sensor.get('id')} below threshold"
    if high is not None and value > high:
        breach = abs(value - high) / (abs(high) or 1)
        return -min(35, int(breach * 25 + 12)), f"{sensor.get('id')} above threshold"
    return 0, None

def _health_scores_list(email):
    assets = data_table.query(
        KeyConditionExpression='email = :e AND begins_with(sk, :p)',
        ExpressionAttributeValues={':e': email, ':p': 'ASSET#'}
    )['Items']
    sensors = data_table.query(
        KeyConditionExpression='email = :e AND begins_with(sk, :p)',
        ExpressionAttributeValues={':e': email, ':p': 'SENSOR#'}
    )['Items']

    status_penalty = {'ok': 0, 'info': 0, 'warning': -18, 'critical': -45, 'offline': -60}
    scores = []
    for a in assets:
        a_sensors = [s for s in sensors if s.get('assetId') == a.get('id')]
        risk = []
        penalty = status_penalty.get(a.get('status', 'ok'), 0)
        if a.get('status') == 'warning':
            risk.append('asset status: warning')
        if a.get('status') == 'critical':
            risk.append('asset status: critical')
        for s in a_sensors:
            dp, msg = _sensor_score(s, s.get('lastValue'))
            penalty += dp
            if msg:
                risk.append(msg)
        score = max(5, min(99, 85 + penalty))
        trend = 'critical' if score < 40 else ('declining' if score < 60 else ('stable' if score < 85 else 'rising'))
        scores.append({
            'assetId': a.get('id'),
            'assetName': a.get('name'),
            'assetType': a.get('type'),
            'floorLevel': a.get('floorLevel'),
            'score': score,
            'trend': trend,
            'topRisks': risk[:3],
            'lastUpdated': datetime.utcnow().isoformat() + 'Z',
        })
    return response(200, {'scores': scores, 'generatedAt': datetime.utcnow().isoformat() + 'Z'})

def _health_score_detail(email, asset_id):
    asset = data_table.get_item(Key={'email': email, 'sk': f'ASSET#{asset_id}'})
    if 'Item' not in asset:
        return response(404, {'error': 'Asset not found'})
    a = asset['Item']
    sensors = data_table.query(
        KeyConditionExpression='email = :e AND begins_with(sk, :p)',
        ExpressionAttributeValues={':e': email, ':p': 'SENSOR#'}
    )['Items']
    a_sensors = [s for s in sensors if s.get('assetId') == asset_id]

    trends = []
    for s in a_sensors:
        readings = readings_table.query(
            KeyConditionExpression='email = :e',
            ExpressionAttributeValues={':e': email},
            ScanIndexForward=False, Limit=200
        )['Items']
        rr = sorted([r for r in readings if r.get('sensorId') == s.get('id')],
                    key=lambda r: r.get('timestamp', ''))[-20:]
        values = [{'timestamp': r.get('timestamp'), 'value': float(r.get('value', 0))} for r in rr]
        baseline = s.get('thresholdLow') or 0
        current_avg = float(sum(v['value'] for v in values) / len(values)) if values else 0.0
        slope = 0.0
        if len(values) >= 2:
            slope = (values[-1]['value'] - values[0]['value']) / max(1, len(values))
        healthy = True
        if s.get('thresholdHigh') is not None and current_avg > s['thresholdHigh']:
            healthy = False
        trends.append({
            'sensorType': s.get('type'),
            'unit': s.get('unit'),
            'values': values,
            'baseline': baseline,
            'currentAvg': current_avg,
            'slope': slope,
            'healthy': healthy,
        })

    detail = {'assetId': a.get('id'), 'assetName': a.get('name'),
              'assetType': a.get('type'), 'floorLevel': a.get('floorLevel'),
              'trends': trends, 'lastUpdated': datetime.utcnow().isoformat() + 'Z'}
    # Reuse the same rule base as the list view so the detail header matches the cards
    status_penalty = {'ok': 0, 'info': 0, 'warning': -18, 'critical': -45, 'offline': -60}
    penalty = status_penalty.get(a.get('status', 'ok'), 0)
    risk = []
    if a.get('status') == 'warning':
        risk.append('asset status: warning')
    if a.get('status') == 'critical':
        risk.append('asset status: critical')
    for s in a_sensors:
        dp, msg = _sensor_score(s, s.get('lastValue'))
        penalty += dp
        if msg:
            risk.append(msg)
    detail['score'] = max(5, min(99, 85 + penalty))
    detail['trend'] = 'critical' if detail['score'] < 40 else ('declining' if detail['score'] < 60 else ('stable' if detail['score'] < 85 else 'rising'))
    detail['topRisks'] = risk[:3]
    return response(200, detail)

# ──────────────────────────────────────────────────
# Demo simulator (workers sim / anomaly injection)
# ──────────────────────────────────────────────────

SCENARIOS = {
    'normal': ('Normal', {}),
    'chiller_failure': ('Chiller Failure', {
        'CH-BAS-01': 'critical', 'CH-BAS-02': 'critical',
        'PUM-CHW-01': 'warning',
    }),
    'power_surge_floor_3': ('Power Surge', {
        'AHU-WST-01': 'warning', 'LTG-F3-01': 'warning',
    }),
    'severe_temp_breach': ('Temp Breach', {
        'AHU-EST-01': 'warning', 'AHU-EST-02': 'warning',
    }),
}

SCENARIO_ALERTS = {
    'chiller_failure': ('CH-BAS-01', 'critical', 'Chiller load exceeded — condenser fouling suspected'),
    'power_surge_floor_3': ('AHU-WST-01', 'high', 'Power surge detected on Level 3 distribution board'),
    'severe_temp_breach': ('AHU-EST-01', 'high', 'Severe temperature breach — supply air above setpoint'),
    'normal': None,
}

def handle_demo(email, method, body, path):
    if method != 'POST':
        return response(405, {'error': 'Method not allowed'})

    if path.endswith('/scenario'):
        scenario = body.get('scenario') if isinstance(body, dict) else None
        if scenario not in SCENARIOS:
            return response(400, {'error': f"unknown scenario: {scenario}"})
        label, status_map = SCENARIOS[scenario]
        for asset_id, status in status_map.items():
            data_table.update_item(
                Key={'email': email, 'sk': f'ASSET#{asset_id}'},
                UpdateExpression='SET #s = :s, updatedAt = :ua',
                ExpressionAttributeValues={':s': status, ':ua': datetime.utcnow().isoformat() + 'Z'},
                ExpressionAttributeNames={'#s': 'status'},
            )
        # Reset everything else to ok on 'normal'
        if scenario == 'normal':
            assets = data_table.query(
                KeyConditionExpression='email = :e AND begins_with(sk, :p)',
                ExpressionAttributeValues={':e': email, ':p': 'ASSET#'}
            )['Items']
            for a in assets:
                data_table.update_item(
                    Key={'email': email, 'sk': a['sk']},
                    UpdateExpression='SET #s = :s, updatedAt = :ua',
                    ExpressionAttributeValues={':s': 'ok', ':ua': datetime.utcnow().isoformat() + 'Z'},
                    ExpressionAttributeNames={'#s': 'status'},
                )
        # Alert side-effects
        alert = SCENARIO_ALERTS.get(scenario)
        if alert:
            asset_id, severity, message = alert
            aid = f'scenario-{scenario}-{uuid.uuid4().hex[:6]}'
            data_table.put_item(Item={
                'email': email, 'sk': f'ALERT#{aid}', 'id': aid,
                'assetId': asset_id, 'severity': severity, 'status': 'open',
                'message': message,
                'createdAt': datetime.utcnow().isoformat() + 'Z',
            })
        return response(200, {'success': True, 'scenario': label})

    if path.endswith('/inject-reading'):
        sensor_id = body.get('sensorId')
        value = body.get('value')
        if not sensor_id or value is None:
            return response(400, {'error': 'sensorId and value required'})
        now = datetime.utcnow().isoformat() + 'Z'
        readings_table.put_item(Item={
            'email': email, 'timestamp': now,
            'sensorId': sensor_id, 'assetId': body.get('assetId', ''),
            'value': Decimal(str(value)), 'unit': body.get('unit', ''),
            'quality': body.get('quality', 'good'),
        })
        # Upsert sensor lastValue so charts move — but ONLY if the sensor row
        # actually exists. update_item without a condition silently UPSERTS a
        # partial row ({email, sk, lastValue, lastReadingAt}) when the id is
        # unknown (e.g. demo controls injecting 'anomaly-demo-test'), and the
        # frontend's formatSensorValue crashes on the missing 'unit'. Guard with
        # attribute_exists; on ConditionalCheckFailedException (unknown sensor)
        # write a COMPLETE row instead.
        try:
            data_table.update_item(
                Key={'email': email, 'sk': f'SENSOR#{sensor_id}'},
                UpdateExpression='SET lastValue = :v, lastReadingAt = :t',
                ConditionExpression='attribute_exists(sk)',
                ExpressionAttributeValues={':v': Decimal(str(value)), ':t': now},
            )
        except Exception as e:
            if getattr(e, 'response', {}).get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                raise
            data_table.put_item(Item={
                'email': email, 'sk': f'SENSOR#{sensor_id}', 'id': sensor_id,
                'assetId': body.get('assetId', ''), 'type': body.get('type', 'temperature'),
                'unit': body.get('unit', '°C'), 'status': 'warning',
                'thresholdHigh': 28, 'lastValue': Decimal(str(value)),
                'lastReadingAt': now, 'createdAt': now,
            })
        return response(200, {'success': True})

    if path.endswith('/inject-alert'):
        aid = f'anomaly-{uuid.uuid4().hex[:6]}'
        data_table.put_item(Item={
            'email': email, 'sk': f'ALERT#{aid}', 'id': aid,
            'assetId': body.get('assetId', 'AHU-EST-01'),
            'sensorId': body.get('sensorId', 'anomaly-demo-test'),
            'severity': body.get('severity', 'critical'),
            'status': 'open',
            'message': body.get('message', 'Critical anomaly injected via demo control'),
            'createdAt': datetime.utcnow().isoformat() + 'Z',
        })
        return response(200, {'success': True})

    return response(404, {'error': 'Not found'})


def handle_ai(email, method, body, path):
    """POST /ai/copilot/query — route AI questions to the shared ai_service
    (dtfm-api and dtfm-ai share the same IAM role, so quota + Bedrock work
    directly here; no cross-lambda invoke or extra gateway plumbing)."""
    if method != 'POST':
        return response(405, {'error': 'Method not allowed'})

    # SSE streaming isn't supported through the REST proxy (no gateway
    # streaming integration) — return 404 so the copilot page falls back
    # to the non-streaming POST.
    if path.endswith('/stream'):
        return response(404, {'error': 'Streaming unavailable; use POST /api/ai/copilot/query'})

    import ai_service
    question = str(body.get('question', '')).strip()
    if not question:
        question = str(body.get('query', '')).strip()
    if not question:
        return response(400, {'error': 'question is required'})

    if not ai_service.check_quota(email):
        return response(429, {'error': 'Daily query limit reached (25/day)'})

    answer = ai_service.call_bedrock(question, email)
    return response(200, {'answer': answer, 'model': ai_service.BEDROCK_MODEL})