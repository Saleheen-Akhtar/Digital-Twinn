import json
import os
from datetime import datetime

import boto3
import functools

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Allow-Methods': 'OPTIONS,POST',
}

REGION = os.environ.get('AWS_REGION', 'us-east-1')
USAGE_TABLE = os.environ.get('USAGE_TABLE', 'dtfm-tenant-data')
DAILY_LIMIT = int(os.environ.get('AI_DAILY_LIMIT', '25'))
BEDROCK_MODEL = os.environ.get('BEDROCK_MODEL', 'anthropic.claude-3-haiku-20240307-v1:0')
BEDROCK_MAX_TOKENS = int(os.environ.get('BEDROCK_MAX_TOKENS', '1024'))

dynamodb = boto3.resource('dynamodb')
users_table = dynamodb.Table('dtfm-users')


def get_user_email(event):
    """Same opaque-session-token lookup as api.py — no JWT in the serverless stack."""
    token = event.get('headers', {}).get('Authorization', '').replace('Bearer ', '')
    if not token:
        return None
    result = users_table.scan(
        FilterExpression='session_token = :t',
        ExpressionAttributeValues={':t': token}
    )
    return result['Items'][0]['email'] if result['Items'] else None


def check_quota(email: str) -> bool:
    """Atomically increment today's counter; False when over the daily limit (fail-closed)."""
    day = datetime.utcnow().strftime('%Y-%m-%d')
    try:
        dynamodb.Table(USAGE_TABLE).update_item(
            Key={'email': email, 'sk': f'AIQUOTA#{day}'},
            UpdateExpression='ADD qty :one',
            ExpressionAttributeValues={':one': 1, ':limit': DAILY_LIMIT},
            ConditionExpression='attribute_not_exists(qty) OR qty < :limit',
        )
        return True
    except Exception as exc:
        code = getattr(exc, 'response', {}).get('Error', {}).get('Code')
        if code == 'ConditionalCheckFailedException':
            return False
        raise  # any other DDB error = fail closed, never open


def call_bedrock(query: str) -> str:
    """Invoke Anthropic Claude via AWS Bedrock (no API keys, IAM role auth)."""
    client = boto3.client('bedrock-runtime', region_name=REGION)
    body = json.dumps({
        'anthropic_version': 'bedrock-2023-05-31',
        'max_tokens': BEDROCK_MAX_TOKENS,
        'system': 'You are a facility management AI assistant for Digital Twin FM. '
                  'Answer concisely and factually about facility operations.',
        'messages': [{'role': 'user', 'content': query}],
    })
    resp = client.invoke_model(
        modelId=BEDROCK_MODEL,
        contentType='application/json',
        accept='application/json',
        body=body,
    )
    out = json.loads(resp['body'].read())
    return ''.join(b['text'] for b in out.get('content', []) if b.get('type') == 'text').strip()


def response(status, body):
    return {'statusCode': status, 'headers': CORS_HEADERS, 'body': json.dumps(body)}


def lambda_handler(event, context):
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': ''}

    try:
        email = get_user_email(event)
        if not email:
            return response(401, {'error': 'Unauthorized: valid session token required'})

        if not check_quota(email):
            return response(429, {'error': f'Daily query limit reached ({DAILY_LIMIT}/day)'})

        body = json.loads(event.get('body', '{}'))
        query = str(body.get('query', '')).strip()
        if not query:
            return response(400, {'error': 'query is required'})

        answer = call_bedrock(query)
        return response(200, {'response': answer, 'model': BEDROCK_MODEL})
    except Exception as e:
        return response(500, {'error': str(e)})