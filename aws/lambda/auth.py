import json
import boto3
import uuid
from datetime import datetime
import secrets
import functools

dynamodb = boto3.resource('dynamodb')
users_table = dynamodb.Table('dtfm-users')

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Allow-Methods': 'OPTIONS,POST,GET'
}

@functools.lru_cache(maxsize=1)
def get_frappe_api_token():
    """Fetch Frappe API token from Secrets Manager."""
    client = boto3.client('secretsmanager', region_name='us-east-1')
    response = client.get_secret_value(
        SecretId='arn:aws:secretsmanager:us-east-1:976193236457:secret:opencrm/frappe-api-key-iQgSaZ'
    )
    secret = response['SecretString'].strip()
    return secret if secret.startswith('token ') else f'token {secret}'

def generate_otp():
    import random
    return str(random.randint(100000, 999999))

def response(status, body):
    return {'statusCode': status, 'headers': CORS_HEADERS, 'body': json.dumps(body)}

def lambda_handler(event, context):
    method = event.get('httpMethod', '')
    if method == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': ''}
    
    path = event.get('path', '')
    try:
        body = json.loads(event.get('body', '{}'))
        
        if '/register' in path:
            return handle_register(body)
        elif '/verify' in path:
            return handle_verify(body)
        elif '/login' in path:
            return handle_login(body)
        return response(404, {'error': 'Not found'})
    except Exception as e:
        return response(500, {'error': str(e)})

def handle_register(body):
    email = body['email'].lower().strip()
    name = body.get('name', 'User')
    mobile = body.get('mobile', '')
    otp = generate_otp()
    
    # Send OTP via n8n webhook
    try:
        import urllib3
        http = urllib3.PoolManager()
        http.request('POST',
            'https://n8n.digitransolutions.in/webhook/digitranva-lead-intake',
            headers={'Content-Type': 'application/json', 'Authorization': get_frappe_api_token()},
            body=json.dumps({
                'first_name': name.split()[0],
                'last_name': ' '.join(name.split()[1:]) if len(name.split()) > 1 else '',
                'email': email, 'mobile': mobile, 'organization': 'DTFM',
                'action': 'create_lead', 'otp': otp, 'send_otp': True
            }))
    except Exception as e:
        print(f"n8n webhook failed: {e}")
    
    existing = users_table.get_item(Key={'email': email})
    if 'Item' in existing:
        users_table.update_item(
            Key={'email': email},
            UpdateExpression='SET otp = :otp, otp_created_at = :ts',
            ExpressionAttributeValues={':otp': otp, ':ts': datetime.utcnow().isoformat()}
        )
        return response(200, {'requiresOTP': True, 'message': 'OTP sent to email'})
    
    users_table.put_item(Item={
        'email': email, 'name': name, 'mobile': mobile, 'otp': otp,
        'otp_created_at': datetime.utcnow().isoformat(),
        'created_at': datetime.utcnow().isoformat(), 'verified': False
    })
    return response(200, {'requiresOTP': True, 'message': 'OTP sent to email'})

def handle_verify(body):
    email = body['email'].lower().strip()
    otp = body['otp']
    
    user = users_table.get_item(Key={'email': email})
    if 'Item' not in user:
        return response(404, {'error': 'User not found'})
    if user['Item'].get('otp') != otp:
        return response(401, {'error': 'Invalid OTP'})
    
    token = secrets.token_urlsafe(32)
    users_table.update_item(
        Key={'email': email},
        UpdateExpression='SET verified = :v, session_token = :t, last_login = :ts REMOVE otp',
        ExpressionAttributeValues={':v': True, ':t': token, ':ts': datetime.utcnow().isoformat()}
    )
    return response(200, {'token': token, 'user': {'email': email, 'name': user['Item']['name']}})

def handle_login(body):
    email = body['email'].lower().strip()
    user = users_table.get_item(Key={'email': email})
    if 'Item' not in user:
        return response(404, {'error': 'User not found. Please register first.'})

    otp = generate_otp()
    users_table.update_item(
        Key={'email': email},
        UpdateExpression='SET otp = :otp, otp_created_at = :ts',
        ExpressionAttributeValues={':otp': otp, ':ts': datetime.utcnow().isoformat()}
    )

    try:
        import urllib3
        http = urllib3.PoolManager()
        http.request('POST',
            'https://n8n.digitransolutions.in/webhook/digitranva-lead-intake',
            headers={'Content-Type': 'application/json', 'Authorization': get_frappe_api_token()},
            body=json.dumps({'email': email, 'otp': otp, 'send_otp': True, 'action': 'send_otp'}))
    except Exception as e:
        print(f"n8n webhook failed: {e}")

    return response(200, {'requiresOTP': True})
