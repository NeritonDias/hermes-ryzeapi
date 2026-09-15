"""Discoverable without credentials; activation remains fail-closed."""
import os
from .settings import configured as _configured, load, directory

REQUIRED = ['RYZEAPI_INSTANCE', 'RYZEAPI_INSTANCE_TOKEN', 'RYZEAPI_WEBHOOK_SECRET', 'RYZEAPI_ALLOWED_USERS']

def configured(config=None): return _configured()

def register(ctx):
    from .adapter import RyzeAdapter, standalone_send
    from .tools import register_tools
    if hasattr(ctx,'register_tool'):register_tools(ctx)
    # Honor the native gateway authorization contract. Only the non-secret
    # allowlist is bridged, in this process, with private settings authoritative.
    if (directory() / 'settings.json').exists():
        value = load()
        os.environ['RYZEAPI_ALLOWED_USERS'] = value.get('allowed_users', '') if value.get('enabled') else ''
    ctx.register_platform(name='ryzeapi', label='WhatsApp — RyzeAPI',
        adapter_factory=RyzeAdapter, check_fn=lambda: True, is_connected=configured,
        required_env=REQUIRED, allowed_users_env='RYZEAPI_ALLOWED_USERS',
        env_enablement_fn=lambda: {'allowed_users': load().get('allowed_users', '')} if configured() else None,
        max_message_length=4000, pii_safe=True, emoji='📱', allow_update_command=False,
        standalone_sender_fn=standalone_send,
        platform_hint='RyzeAPI: use as ferramentas ryzeapi_send_buttons/list/poll/carousel/form/contact/location/media/sticker/pix/event/reaction/status/text para envios reais; consulte skill_view("ryzeapi:ryzeapi") e tool_search. Não simule botões com texto. DMs somente para números autorizados. Grupos exigem modo Ouvir e responder; Só ouvir nunca permite envio. Use o JID completo @g.us, não exponha dados privados em grupos. Status exige aprovação explícita fora de grupos.')
