"""Private, atomic settings shared by the dashboard and gateway."""
import json, os, tempfile
from pathlib import Path
from hermes_constants import get_hermes_home

def directory():
    return get_hermes_home() / 'ryzeapi'

def load():
    path = directory() / 'settings.json'
    if path.exists():
        value = json.loads(path.read_text())
        if not isinstance(value, dict): raise ValueError('Invalid RyzeAPI settings')
        return value
    # Preserve the previously shipped environment-based setup, if it was configured.
    from gateway.platforms._shared import get_scoped_secret
    values = {key: get_scoped_secret(env, '') for key, env in {
        'instance': 'RYZEAPI_INSTANCE', 'instance_token': 'RYZEAPI_INSTANCE_TOKEN',
        'webhook_secret': 'RYZEAPI_WEBHOOK_SECRET', 'allowed_users': 'RYZEAPI_ALLOWED_USERS'}.items()}
    values['enabled'] = all(values.values())
    return values

def save(value):
    folder = directory()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix='.settings-', dir=folder)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, folder / 'settings.json')
    finally:
        if os.path.exists(name): os.unlink(name)

def configured():
    value = load()
    return bool(value.get('enabled') and all(value.get(k) for k in
        ['instance', 'instance_token', 'webhook_secret', 'allowed_users']))

def recipient_list(value):
    """Legacy private channels default to replying only to their operators."""
    return value.get('allowed_recipients', value.get('allowed_users', ''))

def buffer_seconds(value):
    seconds = value.get('buffer_seconds', 10)
    return seconds if type(seconds) is int and 0 <= seconds <= 60 else 10

def echo_transcripts(value):
    # Preserve the previously enabled transcript echo; malformed values fail closed.
    return value.get('echo_transcripts', True) is True
