"""Deployment-specific settings, separate from credentials and checked-in code."""
import json,re,os,tempfile
from urllib.parse import urlsplit
from .settings import directory

DEFAULTS={'public_origin':'http://localhost:9119','webhook_url':'','listener_port':9131, 'listener_host':'127.0.0.1', 'lifecycle':'auto',
          'owner_subject':'', 'owner_issuer':'',
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
        hook=urlsplit(result['webhook_url'])
        # An explicit HTTPS port is valid for the deployment's own public Webapp.
        https_port = (origin.port or 443) if hook.netloc == origin.netloc and origin.scheme == 'https' else 443
        public_url(result['webhook_url'], https_port=https_port)
        if hook.path!='/ryzeapi/events' or hook.query or hook.fragment:
            raise ValueError('webhook_url must use HTTPS and the exact /ryzeapi/events path')
    if type(result['listener_port']) is not int or not 1024<=result['listener_port']<=65535:
        raise ValueError('listener_port must be an integer between 1024 and 65535')
    if result['listener_host'] not in ('127.0.0.1', '0.0.0.0'):
        raise ValueError('Invalid listener_host')
    if result['lifecycle'] not in ('auto', 'coolify', 'systemd'):
        raise ValueError('Invalid lifecycle')
    if any(not isinstance(result[key], str) for key in ('owner_subject', 'owner_issuer')):
        raise ValueError('Invalid OIDC owner')
    if bool(result['owner_subject']) != bool(result['owner_issuer']):
        raise ValueError('Set both owner_subject and owner_issuer')
    if not isinstance(result['gateway_service'],str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}\.service',result['gateway_service']):
        raise ValueError('gateway_service must be a systemd user service name, not a command')
    if not isinstance(result['webhook_label'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',result['webhook_label']):
        raise ValueError('Invalid webhook_label')
    return result

def webapp_origin():
    """Read the active Hermes profile, never HTTP Host or forwarded headers."""
    try:
        from gateway.webapp_listener import webapp_settings
    except ImportError:
        return ''
    from hermes_constants import get_hermes_home
    try:
        url = urlsplit(webapp_settings(get_hermes_home()).public_url or '')
        if url.scheme != 'https' or not url.hostname or url.username is not None or url.password is not None:
            return ''
        # Accessing port validates its numeric value and supported range.
        if url.port == 0:
            return ''
    except ValueError:
        return ''
    return f'https://{url.netloc}'


def load():
    path = directory() / 'deployment.json'
    value = json.loads(path.read_text()) if path.exists() else {}
    if isinstance(value, dict) and not value.get('public_origin'):
        value['public_origin'] = webapp_origin() or DEFAULTS['public_origin']
    return validate(value)

def health_url():return 'http://127.0.0.1:'+str(load()['listener_port'])+'/health'

def save(value):
    config = validate(value)
    folder = directory()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix='.deployment-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, folder / 'deployment.json')
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
