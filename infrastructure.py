"""Deployment-specific settings, separate from credentials and checked-in code."""
import json,re
from urllib.parse import urlsplit
from .settings import directory

DEFAULTS={'public_origin':'http://localhost:9119','webhook_url':'','listener_port':9120,
          'gateway_service':'hermes-gateway.service','webhook_label':'hermes-ryzeapi'}

def validate(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise ValueError('Unknown deployment configuration')
    result={**DEFAULTS,**value}
    origin=urlsplit(result['public_origin'])
    if (origin.scheme not in ('http','https') or not origin.hostname or origin.username or origin.password
        or origin.path or origin.query or origin.fragment
        or (origin.scheme=='http' and origin.hostname not in ('localhost','127.0.0.1','::1'))):
        raise ValueError('public_origin must be an HTTPS origin (HTTP allowed only on loopback), without a path')
    if result['webhook_url']:
        from .outbound import public_url
        public_url(result['webhook_url'])
        hook=urlsplit(result['webhook_url'])
        if hook.path!='/ryzeapi/events' or hook.query or hook.fragment:
            raise ValueError('webhook_url must use HTTPS and the exact /ryzeapi/events path')
    if type(result['listener_port']) is not int or not 1024<=result['listener_port']<=65535:
        raise ValueError('listener_port must be an integer between 1024 and 65535')
    if not isinstance(result['gateway_service'],str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}\.service',result['gateway_service']):
        raise ValueError('gateway_service must be a systemd user service name, not a command')
    if not isinstance(result['webhook_label'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',result['webhook_label']):
        raise ValueError('Invalid webhook_label')
    return result

def load():
    path=directory()/'deployment.json'
    return validate(json.loads(path.read_text()) if path.exists() else {})

def health_url():return 'http://127.0.0.1:'+str(load()['listener_port'])+'/health'
