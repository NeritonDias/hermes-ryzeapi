"""Current official RyzeAPI HTTP contract; no old Claude credentials."""
import asyncio, re, time
from urllib.parse import quote
import httpx
from .core import phone, lid, authorized_phone, MAX_BODY
from .groups import group_id
from .telemetry import EVENTS

BASE = 'https://ryzeapi.cloud'

class RyzeError(Exception):
    def __init__(self, message, *, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

class RyzeClient:
    def __init__(self, instance, token, *, transport=None, max_body=MAX_BODY, success_codes=(200,)):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', instance or ''):
            raise ValueError('Invalid RyzeAPI instance name')
        if not token or '\n' in token or '\r' in token: raise ValueError('Missing/invalid instance token')
        self.instance = instance
        self.own_number = ''
        self.rate_reset = 0
        self.max_body = max_body
        self.success_codes = success_codes
        self.http = httpx.AsyncClient(base_url=BASE, headers={'token': token},
            timeout=30, follow_redirects=False, transport=transport, trust_env=False)

    async def request(self, method, path, payload=None):
        data = await self.envelope(method, path, payload=payload)
        return data.get('data')

    async def envelope(self, method, path, *, payload=None, params=None, timeout=30, retry_get=True):
        # Only GETs are replay-safe. Sending POSTs are never retried here, even 429.
        for attempt in range(2 if method == 'GET' and retry_get else 1):
            remaining = self.rate_reset - time.time()
            if remaining > 0:
                if method != 'GET' or remaining > 2:
                    raise RyzeError('RyzeAPI rate limited; request not sent', status=429, retry_after=remaining)
                await asyncio.sleep(remaining)
            try:
                return await self._envelope_once(method, path, payload=payload, params=params, timeout=timeout)
            except RyzeError as exc:
                retryable = exc.status in {429, 500, 502, 503, 504} or (exc.status == 404 and '/chat/base64/' in path)
                if method != 'GET' or not retry_get or attempt or not retryable: raise
                pause = exc.retry_after if exc.retry_after is not None else .5
                if pause > 2: raise
                await asyncio.sleep(max(.1, pause))

    async def _envelope_once(self, method, path, *, payload=None, params=None, timeout=30):
        try:
            async with self.http.stream(method, path, json=payload, params=params, timeout=timeout) as response:
                status = response.status_code
                retry_after = None
                try:
                    if status == 429 or response.headers.get('X-RateLimit-Remaining') == '0':
                        retry_after = max(0, min(300, float(response.headers.get('X-RateLimit-Reset', time.time()+1)) - time.time()))
                        self.rate_reset = time.time() + retry_after
                except (TypeError, ValueError): pass
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > self.max_body: raise RyzeError('RyzeAPI response exceeds safe limit')
        except httpx.TimeoutException as exc:
            raise RyzeError('RyzeAPI timeout; delivery is uncertain — do not blindly retry a send') from exc
        except httpx.HTTPError as exc:
            raise RyzeError('RyzeAPI network failure; delivery may be uncertain') from exc
        if status not in self.success_codes:
            raise RyzeError(f'RyzeAPI HTTP {status}; response body omitted to protect secrets', status=status, retry_after=retry_after)
        import json
        try: data = json.loads(content)
        except ValueError as exc: raise RyzeError('RyzeAPI returned invalid JSON') from exc
        if not isinstance(data, dict) or data.get('success') is not True:
            raise RyzeError('RyzeAPI operation was not confirmed successful')
        return data

    async def ensure_websocket(self):
        expected = {'enabled': True, 'events': EVENTS, 'mediaBase64': True}
        actual = (await self.envelope('GET', f'/api/events/getWebsocket/{self.instance}')).get('websocket') or {}
        if all(actual.get(k) == v for k, v in expected.items()): return
        await self.envelope('POST', f'/api/events/websocket/{self.instance}', payload=expected)
        actual = (await self.envelope('GET', f'/api/events/getWebsocket/{self.instance}')).get('websocket') or {}
        if any(actual.get(k) != v for k, v in expected.items()):
            raise RyzeError('RyzeAPI WebSocket configuration not confirmed')

    async def contact(self, identifier):
        data = await self.envelope('GET', f'/api/chat/contacts/{self.instance}', params={'number': identifier}, timeout=8)
        return data.get('contact') or {}

    async def send_rich(self, kind, number, payload):
        from .outbound import prepare, KINDS
        body,warnings=prepare(kind,payload,number)
        result=await self.envelope('POST',f'/api/message/{KINDS[kind][1]}/{self.instance}',
                                   payload=body,timeout=60+body.get('delay',0))
        data=result.get('data')
        mid=data.get('messageId') if isinstance(data,dict) else None
        if result.get('status')!='sent' or not isinstance(mid,str) or not 1<=len(mid)<=256:
            raise RyzeError('RyzeAPI send response is unconfirmed; do not resend blindly')
        return {'success':True,'message_id':mid,'format':kind,'status':'accepted',
                'delivered':False,'warnings':warnings}

    async def own_lid_for(self, number):
        """Resolve only the connected phone's authenticated binding, never bare LID digits."""
        number = phone(number)
        if not number: return ''
        contact = await self.contact(number)
        if isinstance(contact,dict) and contact.get('found') is True:
            if authorized_phone(contact.get('jid'),{number}) and lid(contact.get('lid')):
                return lid(contact['lid'])
        # The contact store may not include the bot itself. The own-profile route
        # is the documented fallback, with the same phone binding required.
        profile = (await self.envelope('GET',f'/api/profile/getAccount/{self.instance}',timeout=12)).get('profile')
        if not isinstance(profile,dict): return ''
        identifiers = [profile[k] for k in ('jid','phoneNumber') if profile.get(k)]
        if identifiers and all(authorized_phone(n,{number}) for n in identifiers):
            return lid(profile.get('lid'))
        return ''

    async def connection_state(self):
        data = await self.envelope('GET', '/api/instance/list', params={'instanceName':self.instance}, timeout=8)
        for item in data.get('instances') or []:
            if isinstance(item,dict) and item.get('name') == self.instance:
                self.own_number = phone((item.get('connection') or {}).get('numberJid') or item.get('numberJid'))
                state = (item.get('connection') or {}).get('state') or item.get('status')
                return {'loggedout':'logged_out','qr':'qr_ready'}.get(state,state)
        self.own_number = ''
        return 'unknown'

    async def media_base64(self, message_id):
        return await self.envelope('GET', f'/api/chat/base64/{self.instance}', params={'messageId': message_id}, timeout=15)

    async def message_status(self, message_id):
        return await self.envelope('GET', f'/api/chat/status/{self.instance}', params={'messageId':message_id}, timeout=8)

    async def presence(self, number):
        if not (phone(number) or group_id(number)): raise ValueError('Invalid recipient')
        await self.envelope('POST', f'/api/chat/presence/{self.instance}',
                            payload={'number': number, 'state': 'typing', 'duration': 5}, timeout=6)

    async def send_media(self, number, encoded, kind, mime, filename, caption=None, reply_to=None, *, is_voice=False):
        if not (phone(number) or group_id(number)) or kind not in {'image', 'video', 'audio', 'document'}:
            raise ValueError('Invalid media destination or type')
        payload = {'number': number, 'mediaType': kind, 'mediaBase64': encoded,
                   'mimeType': mime, 'fileName': filename, 'isVoice': kind == 'audio' and is_voice}
        if caption: payload['message'] = caption
        if reply_to: payload['replyTo'] = reply_to
        result = await self.envelope('POST', f'/api/message/media/{self.instance}', payload=payload, timeout=120)
        mid = (result.get('data') or {}).get('messageId')
        if not mid: raise RyzeError('Media send returned no messageId; no automatic retry')
        return str(mid)

    async def send_text(self, number, message, reply_to=None):
        number = phone(number) or group_id(number)
        if not number or not isinstance(message, str) or not message.strip(): raise ValueError('Invalid recipient or message')
        payload = {'number': number, 'message': message, 'linkPreview': False}
        if reply_to: payload['replyTo'] = reply_to
        data = await self.request('POST', f'/api/message/text/{quote(self.instance, safe="")}', payload)
        mid = data.get('messageId') if isinstance(data, dict) else None
        if not mid: raise RyzeError('Send returned no messageId; delivery uncertain, no automatic retry')
        return str(mid)

    async def close(self): await self.http.aclose()
