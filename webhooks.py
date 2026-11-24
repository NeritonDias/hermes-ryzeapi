"""Ownership checks shared by the control plane and the receiver at startup."""
import hmac

from .telemetry import MESSAGE_EVENTS


def owned_hook(value, hook, label, url):
    secret = value.get('webhook_secret')
    return (bool(secret) and hook.get('label') == label and hook.get('url') == url
            and hmac.compare_digest(str(hook.get('authorization') or '').encode(),
                                    ('Bearer ' + secret).encode()))


def separate_destination(hook, label, url):
    from urllib.parse import urlsplit
    def target(address):
        endpoint = urlsplit(address)
        return (endpoint.scheme.lower(), endpoint.hostname, endpoint.port or 443, endpoint.path.rstrip('/'))
    try:
        return bool(url and hook.get('url') and hook.get('label') != label and target(hook['url']) != target(url))
    except (TypeError, ValueError):
        return False


def confirmed(value, hooks):
    if not isinstance(hooks, list) or not all(isinstance(h, dict) and isinstance(h.get('enabled'), bool) for h in hooks):
        return False
    active = [h for h in hooks if h['enabled']]
    if value.get('independent_webhook'):
        active = [h for h in active if not separate_destination(h, value['hook_label'], value['hook_url'])]
    if len(active) != 1:
        return False
    hook = active[0]
    events = hook.get('events')
    return (owned_hook(value, hook, value['hook_label'], value['hook_url'])
            and hook.get('mediaBase64') is True and hook.get('byEvents') is False
            and isinstance(events, list) and all(isinstance(e, str) for e in events)
            and (not events or set(value.get('hook_events', MESSAGE_EVENTS)).issubset(events)))
