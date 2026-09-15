"""Credential-free envelope validation and durable admission queue."""
from __future__ import annotations
import base64, json, math, re, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path

MAX_BODY = 12 * 1024 * 1024
MAX_MEDIA = 8 * 1024 * 1024
PENDING_TTL = 86400

def validated_base64(encoded, mime):
    if not isinstance(encoded, str): raise ValueError('Missing base64')
    if encoded.startswith('data:'):
        if ';base64,' not in encoded: raise ValueError('Invalid data URI')
        encoded = encoded.split(';base64,', 1)[1]
    if len(encoded) > MAX_MEDIA * 4 // 3 + 4: raise ValueError('Media too large')
    raw = base64.b64decode(encoded, validate=True)
    if not raw or len(raw) > MAX_MEDIA: raise ValueError('Invalid media size')
    if mime == 'application/pdf' and not raw.startswith(b'%PDF-'): raise ValueError('Invalid PDF')
    return encoded

def structured_text(msg):
    """Only documented, bounded fields; a contact card never grants authorization."""
    result = []
    value = msg.get('location')
    if isinstance(value, dict):
        lat, lon = value.get('latitude'), value.get('longitude')
        if type(lat) in (int, float) and type(lon) in (int, float) and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            result.append('[Localização]\n'+str(lat)+', '+str(lon))
            if isinstance(value.get('address'), str): result.append(value['address'][:1000])
    for field, label, keys in (
        ('contact','Contato compartilhado',('display_name','phone_number','vcard')),
        ('button_response','Resposta de botão',('title','body','selected_button_id')),
        ('list_response','Resposta de lista',('title','body'))):
        value = msg.get(field)
        if not isinstance(value, dict): continue
        parts = [value[key][:2000] for key in keys if isinstance(value.get(key), str) and value[key]]
        if field == 'list_response':
            reply = value.get('single_select_reply')
            if isinstance(reply, dict) and isinstance(reply.get('option_name'), str): parts.append(reply['option_name'][:1000])
        if parts: result.append('['+label+']\n'+'\n'.join(parts))
    interactive=msg.get('interactive')
    if isinstance(interactive,dict):
        parts=[key+': '+interactive[key][:2000] for key in ('selectedButtonId','selectedRowId','flow_token')
               if isinstance(interactive.get(key),str) and interactive[key]]
        index=interactive.get('selectedCarouselCardIndex')
        selected=interactive.get('selectedReply')
        if isinstance(selected,dict) and isinstance(selected.get('selectedRowID'),str):
            parts.append('selectedRowId: '+selected['selectedRowID'][:2000])
        if isinstance(interactive.get('title'),str):parts.append('title: '+interactive['title'][:1000])
        if type(index) is int and 0<=index<=100:parts.append('card: '+str(index))
        if parts:result.append('[Resposta interativa — dados do participante]\n'+'\n'.join(parts))
    poll=msg.get('poll')
    if isinstance(poll,dict):
        parts=[poll['title'][:2000]] if isinstance(poll.get('title'),str) else []
        options=poll.get('options')
        if isinstance(options,list):
            for option in options[:12]:
                if isinstance(option,dict) and isinstance(option.get('name'),str):
                    parts.append(option['name'][:1000])
        if parts:result.append('[Enquete]\n'+'\n'.join(parts))
    return '\n'.join(result)[:8000]

def phone(value):
    if not isinstance(value, str): return ''
    if re.fullmatch(r'[1-9][0-9]{7,14}:[0-9]+@s\.whatsapp\.net', value):
        value = value.split(':', 1)[0]
    value = value.removesuffix('@s.whatsapp.net').removeprefix('+')
    return value if re.fullmatch(r'[1-9][0-9]{7,14}', value) else ''

def allowed_numbers(value):
    entries = [part.strip() for part in value.split(',') if part.strip()]
    if not entries or any(not phone(x) for x in entries):
        raise ValueError('RYZEAPI_ALLOWED_USERS must contain explicit international phone numbers')
    return {phone(x) for x in entries}

def phone_aliases(value):
    """Only Brazilian mobile numbers may vary by the inserted ninth digit.

    Never strip arbitrary digits, alter foreign numbers, or turn a LID into a phone.
    """
    number = phone(value)
    result = {number} if number else set()
    ddds = {'11','12','13','14','15','16','17','18','19','21','22','24','27','28',
            '31','32','33','34','35','37','38','41','42','43','44','45','46','47','48','49',
            '51','53','54','55','61','62','63','64','65','66','67','68','69','71','73','74',
            '75','77','79','81','82','83','84','85','86','87','88','89','91','92','93','94',
            '95','96','97','98','99'}
    if number.startswith('55') and number[2:4] in ddds:
        if len(number) == 12 and number[4] in '6789': result.add(number[:4]+'9'+number[4:])
        if len(number) == 13 and number[4] == '9' and number[5] in '6789': result.add(number[:4]+number[5:])
    return result

def authorized_phone(value, allowed):
    """Return the configured principal, not a second session for the alias."""
    matches = sorted(phone_aliases(value) & allowed)
    return matches[0] if matches else ''

def lid(value):
    if not isinstance(value, str): return ''
    match = re.fullmatch(r'([1-9][0-9]{5,19})(?::[0-9]+)?@lid', value)
    return match[1]+'@lid' if match else ''

def canonical_envelope(payload):
    """Accept both the published catalog and the live Ryze envelope (2026-09-15).

    Live: data.{id,direction,timestamp,chat,sender}, data.message.content is text.
    Catalog: those fields live inside data.message, content is {text: ...}.
    Outer routing fields are authoritative for the live layout, never mixed with
    contradictory inner identities. Only vetted metadata is copied downstream.
    """
    if not isinstance(payload, dict): return payload
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('message'), dict): return payload
    if 'direction' not in data: return payload
    msg = dict(data['message'])
    for field in ('id', 'direction', 'timestamp', 'chat', 'sender'):
        msg[field] = data.get(field)
    for field in ('mentions', 'reply', 'interactive', 'button_response', 'list_response'):
        if field in data: msg[field] = data[field]
    if isinstance(msg.get('content'), str): msg['content'] = {'text': msg['content']}
    if msg.get('isEdit') and not msg.get('edit'): msg['edit'] = True
    media = msg.get('media')
    if isinstance(media, dict):
        media = dict(media)
        if 'mimetype' not in media: media['mimetype'] = media.get('mimeType') or media.get('mime_type')
        if 'type' not in media: media['type'] = msg.get('type')
        if media.get('type') == 'audio' and media.get('isVoiceNote') is True:
            media['type'] = 'ptt'  # Hermes only automatically transcribes VOICE, not ordinary audio attachments.
        if 'fileName' not in media: media['fileName'] = media.get('filename') or media.get('file_name')
        msg['media'] = media
    return {**payload, 'data': {'message': msg}}

def normalize(payload, *, instance, allowed, now=None, reasons=None, allow_media_reference=False, allow_mutation=False, group=None):
    """Return only vetted fields, never instanceData.token or raw payload."""
    now = time.time() if now is None else now
    payload = canonical_envelope(payload)
    def reject(reason):
        if reasons is not None: reasons.append(reason)
        return None
    if not isinstance(payload, dict): return reject('invalid_envelope')
    meta, data = payload.get('instanceData'), payload.get('data')
    if not isinstance(meta, dict) or meta.get('instance') != instance: return reject('wrong_instance')
    if payload.get('event') != 'message.exchange' or not isinstance(data, dict): return reject('non_message_event')
    msg = data.get('message')
    if not isinstance(msg, dict): return reject('invalid_message_schema')
    if msg.get('direction') != 'incoming': return reject('outgoing_or_unknown_direction')
    chat, sender = msg.get('chat'), msg.get('sender')
    if not isinstance(chat, dict) or not isinstance(sender, dict): return reject('missing_chat_or_sender')
    is_group = bool(group and chat.get('type')=='group' and chat.get('jid')==group.get('jid'))
    if (chat.get('type') != 'private' and not is_group) or chat.get('isCommunity'): return reject('non_private_chat')
    transport_number = phone(sender.get('jid'))
    number = (transport_number or lid(sender.get('jid'))) if is_group and group.get('senders')=='all' else authorized_phone(transport_number, allowed)
    if not number:
        if reasons is not None: reasons.append('sender_not_allowed_or_unresolved')
        return None
    chat_phone = authorized_phone(chat.get('jid'), allowed)
    # A phone resolved by Ryze may accompany a private chat addressed by LID.
    # Require the exact same sender LID; a random LID is never authorized.
    same_lid = lid(chat.get('jid')) and lid(chat.get('jid')) == lid(sender.get('lid'))
    if not is_group and chat_phone != number and not same_lid:
        if reasons is not None: reasons.append('chat_identity_mismatch')
        return None
    mid = msg.get('id') or data.get('id')
    if not isinstance(mid, str) or not 1 <= len(mid) <= 256: return reject('invalid_message_id')
    try:
        stamp = datetime.fromisoformat(str(msg['timestamp']).replace('Z', '+00:00'))
        if stamp.tzinfo is None: return reject('timestamp_missing_zone')
        age = now - stamp.timestamp()
        if age < -300 or age > 86400: return reject('timestamp_outside_window')
    except (ValueError, KeyError, TypeError): return reject('invalid_timestamp')
    message_kind = msg.get('type', '')
    if not isinstance(message_kind, str): return None
    if message_kind in {'message_revoke', 'message_edit'} or msg.get('edit'):
        if not allow_mutation: return reject('edit_or_revoke')
        edit = msg.get('edit') or {}
        if not isinstance(edit,dict): return reject('invalid_edit')
        revoked = message_kind == 'message_revoke'
        target = mid if revoked else edit.get('original_id')
        text = None if revoked else edit.get('text')
        if not isinstance(target,str) or not 1<=len(target)<=256: return reject('invalid_edit_target')
        if not revoked and (not isinstance(text,str) or not text.strip() or len(text)>32000 or text.lstrip().startswith('/')):
            return reject('invalid_edit_text')
        return dict(id=mid,number=number,target=target,mutation='revoke' if revoked else 'edit',
                    text=text,timestamp=stamp.isoformat())
    content = msg.get('content') or {}
    if not isinstance(content, dict): return None
    text = content.get('text') or ''
    if not isinstance(text, str) or len(text) > 32000: return None
    extra = structured_text(msg)
    if extra: text = (text+'\n'+extra).strip()[:32000]
    media = msg.get('media') or {}
    if not isinstance(media, dict): return None
    # URL-only media is intentionally not fetched (untrusted URL/SSRF/encrypted WA media).
    safe_media = None
    if media:
        mime = media.get('mimetype', '')
        kind = media.get('type', '')
        if not isinstance(kind, str) or kind not in {'image', 'audio', 'ptt', 'document', 'video', 'ptv', 'sticker'}: return reject('unsupported_media_type')
        if not isinstance(mime, str) or not re.fullmatch(r'[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+(?:;[^\r\n]{0,100})?', mime): return None
        mime = mime.split(';')[0].lower()
        expected = {'image': 'image/', 'audio': 'audio/', 'ptt': 'audio/', 'document': '',
                    'video': 'video/', 'ptv': 'video/', 'sticker': 'image/'}[kind]
        if not mime.startswith(expected): return None
        encoded = None
        if media.get('base64'):
            try: encoded = validated_base64(media['base64'], mime)
            except (ValueError, TypeError): return reject('invalid_media')
        elif not allow_media_reference: return reject('media_missing_base64')
        # Preserve a safe filename for documents, never a path supplied by the sender.
        filename = re.sub(r'[^\w. -]', '_', str(media.get('fileName') or 'attachment'))[-120:].lstrip('.') or 'attachment'
        safe_media = {'base64': encoded, 'mime': mime, 'kind': kind, 'filename': filename}
        caption = media.get('caption') or ''
        if not isinstance(caption, str) or len(caption) > 32000: return None
        text = text or caption
    if not text.strip() and not safe_media: return None
    reply = msg.get('reply') or {}
    reply_id = reply.get('message_id') if isinstance(reply, dict) else None
    reply_text = reply.get('text') if isinstance(reply, dict) else None
    return dict(id=mid, number=group['jid'] if is_group else number, transport_number=group['jid'] if is_group else transport_number, text=text,
                group_id=group['jid'] if is_group else None, sender_id=number,
                sender_name=str(sender.get('name') or number)[:200],
                timestamp=stamp.isoformat(), media=safe_media,
                needs_media=bool(safe_media and not safe_media['base64']),
                reply_id=reply_id[:256] if isinstance(reply_id, str) else None,
                reply_text=reply_text[:4000] if isinstance(reply_text, str) else None)

class Inbox:
    """At-most-once admission, not an exactly-once execution/delivery claim.

    Crash during handoff is marked uncertain and never automatically re-executed.
    Only bounded normalized payloads are stored; completed payloads are scrubbed.
    """
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        path.chmod(0o600)
        self.db.execute('CREATE TABLE IF NOT EXISTS inbox (id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL)')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(inbox)')}
        if 'number' not in columns:
            self.db.execute("ALTER TABLE inbox ADD COLUMN number TEXT NOT NULL DEFAULT ''")
            self.db.execute('ALTER TABLE inbox ADD COLUMN is_command INTEGER NOT NULL DEFAULT 0')
            for mid, encoded in self.db.execute("SELECT id,payload FROM inbox WHERE status='pending'").fetchall():
                item = json.loads(encoded)
                self.db.execute('UPDATE inbox SET number=?,is_command=? WHERE id=?',
                    (item.get('number',''), int(item.get('text','').lstrip().startswith('/')), mid))
        self.db.execute('CREATE INDEX IF NOT EXISTS inbox_pending ON inbox(status,number,created)')
        if 'expires_at' not in columns:
            self.db.execute('ALTER TABLE inbox ADD COLUMN expires_at REAL NOT NULL DEFAULT 0')
            self.db.execute('ALTER TABLE inbox ADD COLUMN is_stop INTEGER NOT NULL DEFAULT 0')
            for mid, encoded, created in self.db.execute("SELECT id,payload,created FROM inbox WHERE status IN ('pending','preparing')").fetchall():
                item = json.loads(encoded)
                self.db.execute('UPDATE inbox SET expires_at=?,is_stop=? WHERE id=?',
                    (self.expiration(item, created), int(item.get('text','').strip().lower() == '/stop' and not item.get('media')), mid))
        self.db.execute('CREATE INDEX IF NOT EXISTS inbox_expiration ON inbox(status,expires_at)')
        self.db.execute('CREATE INDEX IF NOT EXISTS inbox_schedule ON inbox(status,created,number,is_command,is_stop,id)')
        self.db.execute('CREATE INDEX IF NOT EXISTS inbox_stop_cutoff ON inbox(number,is_stop,created)')
        if 'last_mutation' not in columns:
            self.db.execute('ALTER TABLE inbox ADD COLUMN last_mutation REAL NOT NULL DEFAULT 0')
        self.db.execute("UPDATE inbox SET status='uncertain', payload='{}' WHERE status='handoff'")
        # Preparation has no agent side effects; only this state may safely resume.
        self.db.execute("UPDATE inbox SET status='pending' WHERE status='preparing'")
        self.db.execute("DELETE FROM inbox WHERE status='admitted' AND created < ?", (time.time()-7*86400,))
        self.db.commit()

    @staticmethod
    def expiration(item, created):
        try: stamp = datetime.fromisoformat(item['timestamp']).timestamp()
        except (KeyError, ValueError, TypeError): return 0
        return min(stamp, created) + PENDING_TTL

    def put(self, item, *, received_at=None):
        if self.db.execute('SELECT 1 FROM inbox WHERE id=?', (item['id'],)).fetchone(): return 'duplicate'
        pending, size = self.db.execute("SELECT count(*),coalesce(sum(length(payload)),0) FROM inbox WHERE status IN ('pending','preparing','handoff')").fetchone()
        created = time.time() if received_at is None else received_at
        encoded = json.dumps(dict(item,received_at=created))
        stop = item.get('text', '').strip().lower() == '/stop' and not item.get('media')
        if not stop and self.db.execute('SELECT 1 FROM inbox WHERE number=? AND is_stop=1 AND created>=? LIMIT 1',(item['number'],created)).fetchone():
            # A slower LID lookup may complete after /stop. Its earlier arrival must
            # remain cancelled, not resurrect work that was still in ingress memory.
            with self.db:
                self.db.execute("INSERT INTO inbox(id,payload,status,created,number,is_command,expires_at,is_stop) VALUES (?,'{}','cancelled',?,?,0,?,0)",
                                (item['id'],created,item['number'],self.expiration(item,created)))
            return 'cancelled'
        # Reserve ten small control slots so saturation cannot disable cancellation.
        if pending >= (110 if stop else 100) or size + len(encoded) > 50 * 1024 * 1024 + (16000 if stop else 0): return 'full'
        self.db.execute("INSERT INTO inbox(id,payload,status,created,number,is_command,expires_at,is_stop) VALUES (?,?, 'pending',?,?,?,?,?)",
            (item['id'], encoded, created, item['number'], int(item.get('text','').lstrip().startswith('/')), self.expiration(item, created), int(stop)))
        self.db.commit()
        return 'queued'

    def mutate(self,item):
        """Only an authorized principal's pending buffer item can change, never a command/handoff."""
        stamp = datetime.fromisoformat(item['timestamp']).timestamp()
        with self.db:
            row = self.db.execute("SELECT payload,is_command,last_mutation,expires_at FROM inbox WHERE id=? AND number=? AND status='pending'",
                                  (item['target'],item['number'])).fetchone()
            if not row or row[1] or stamp<=row[2] or row[3]<=time.time(): return 'ignored'
            original = json.loads(row[0])
            if stamp<datetime.fromisoformat(original['timestamp']).timestamp(): return 'ignored'
            if item['mutation']=='revoke':
                self.db.execute("UPDATE inbox SET status='cancelled',payload='{}',last_mutation=? WHERE id=?",(stamp,item['target']))
                return 'revoked'
            original['text'] = item['text']
            encoded = json.dumps(original)
            size = self.db.execute("SELECT coalesce(sum(length(payload)),0) FROM inbox WHERE status IN ('pending','preparing','handoff')").fetchone()[0]
            if size-len(row[0])+len(encoded)>50*1024*1024: return 'full'
            self.db.execute('UPDATE inbox SET payload=?,last_mutation=? WHERE id=?',(encoded,stamp,item['target']))
            return 'edited'

    def take(self):
        batch = self.take_batch(0, max_items=1)
        return batch[0] if batch else None

    def take_batch(self, seconds, *, now=None, max_items=20, exclude=(), stops_only=False, claim='handoff'):
        """Durable per-principal trailing-edge buffer; duplicates never reset its timer.

        Quiet window is capped by 120s from the oldest pending message. Commands
        bypass the wait and are never joined to normal conversation content.
        """
        now = time.time() if now is None else now
        self.expire(now)
        rows = self.db.execute("SELECT id,number,created,is_command,is_stop FROM inbox WHERE status='pending' ORDER BY created,rowid").fetchall()
        all_rows = rows
        if stops_only:
            rows = [row for row in rows if row[4]]
        else:
            rows = [row for row in rows if row[1] not in exclude]
        chosen = [row for row in rows if row[4]][:1]
        if not chosen:
            groups = {}
            for row in rows: groups.setdefault(row[1], []).append(row)
            for group in groups.values():
                if group[0][3]:
                    chosen = group[:1]
                    break
                # Ordinary commands form a barrier, never overtake earlier text.
                boundary = next((i for i, row in enumerate(group) if row[3]), len(group))
                has_command = boundary < len(group)
                group = group[:boundary]
                if has_command or now - group[-1][2] >= seconds or now - group[0][2] >= 120 or len(group) >= max_items:
                    chosen = group[:1 if seconds == 0 else max_items]
                    break
        batch, total_text = [], 0
        for mid, _, _, _, _ in chosen:
            item = json.loads(self.db.execute('SELECT payload FROM inbox WHERE id=?', (mid,)).fetchone()[0])
            size = len(item.get('text',''))
            if batch and total_text + size > 64000: break
            batch.append(item); total_text += size
        if not batch: return []
        if claim not in {'handoff', 'preparing'}: raise ValueError('Invalid claim state')
        with self.db:
            if chosen[0][4]:
                self._cancel_before_stop(batch[0])
            self.db.executemany("UPDATE inbox SET status=? WHERE id=?", [(claim, item['id']) for item in batch])
        return batch

    def _cancel_before_stop(self, stop):
        # Atomic with claiming /stop, including active preparation, never handoff.
        cutoff = self.db.execute('SELECT created,rowid FROM inbox WHERE id=?', (stop['id'],)).fetchone()
        self.db.execute("UPDATE inbox SET status='cancelled',payload='{}' WHERE number=? AND status IN ('pending','preparing') AND (created < ? OR (created=? AND rowid<?))",
                        (stop['number'], cutoff[0], cutoff[0], cutoff[1]))

    def recover_preparing(self, owned):
        rows = self.db.execute("SELECT id FROM inbox WHERE status='preparing'").fetchall()
        orphaned = [row for row in rows if row[0] not in owned]
        with self.db:
            self.db.executemany("UPDATE inbox SET status='pending' WHERE id=? AND status='preparing'", orphaned)
        return len(orphaned)

    def begin_handoff(self, batch):
        with self.db:
            states = [self.db.execute('SELECT status,expires_at,created FROM inbox WHERE id=?', (item['id'],)).fetchone() for item in batch]
            if any(not row or row[0] != 'preparing' for row in states): return False
            if any(row[1] <= time.time() or row[2] <= time.time()-PENDING_TTL for row in states):
                self.db.executemany("UPDATE inbox SET status='expired',payload='{}' WHERE id=?", [(item['id'],) for item in batch])
                return False
            self.db.executemany("UPDATE inbox SET status='handoff' WHERE id=?", [(item['id'],) for item in batch])
        return True

    def expire(self, now=None):
        now = time.time() if now is None else now
        with self.db:
            self.db.execute("UPDATE inbox SET status='expired',payload='{}' WHERE status='pending' AND expires_at<=?", (now,))
            self.db.execute("UPDATE inbox SET status='expired',payload='{}' WHERE status='pending' AND created<=?", (now-PENDING_TTL,))

    def set_batch_status(self, batch, status, *, scrub=False):
        with self.db:
            for item in batch:
                guard = " AND status NOT IN ('cancelled','expired')" if status not in {'cancelled','expired'} else ''
                if status == 'pending': guard += " AND status='preparing'"
                self.db.execute('UPDATE inbox SET status=?' + (",payload='{}'" if scrub else '') + ' WHERE id=?' + guard,
                                (status, item['id']))

    def housekeeping(self, now=None):
        now = time.time() if now is None else now
        self.expire(now)
        with self.db:
            self.db.execute("DELETE FROM inbox WHERE status IN ('admitted','cancelled','expired') AND created < ?", (now-7*86400,))
            # Keep a longer, payload-free review window for uncertain execution.
            self.db.execute("DELETE FROM inbox WHERE status='uncertain' AND created < ?", (now-30*86400,))

    def finish_batch(self, batch, accepted):
        self.db.executemany('UPDATE inbox SET status=?,payload=? WHERE id=?',
            [('admitted' if accepted else 'uncertain', '{}', item['id']) for item in batch])
        self.db.commit()

    def finish(self, mid, accepted):
        self.db.execute('UPDATE inbox SET status=?, payload=? WHERE id=?',
                        ('admitted' if accepted else 'uncertain', '{}', mid))
        self.db.commit()

    def close(self): self.db.close()
