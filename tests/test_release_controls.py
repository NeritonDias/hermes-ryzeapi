import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

import test_management
from ryzeapi import attachments, infrastructure, management as m, settings


class AttachmentTests(unittest.TestCase):
    def test_only_approved_regular_files(self):
        with TemporaryDirectory() as temp, patch.object(attachments, 'get_hermes_home', return_value=Path(temp)):
            root = attachments.attachment_root()
            root.mkdir(parents=True)
            (root / 'note.txt').write_bytes(b'hello')
            self.assertEqual(attachments.read_attachment('note.txt'), b'hello')
            outside = Path(temp) / 'private.txt'
            outside.write_bytes(b'private')
            (root / 'linked').symlink_to(outside)
            (root / 'dir').symlink_to(Path(temp), target_is_directory=True)
            os.link(outside, root / 'hardlink')
            os.mkfifo(root / 'pipe')
            for path in [outside, '../private.txt', 'linked', 'dir/private.txt', 'hardlink', 'pipe']:
                with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                    attachments.read_attachment(path)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await test_management.ManagementTests.asyncSetUp(self)

    async def asyncTearDown(self):
        await test_management.ManagementTests.asyncTearDown(self)

    async def activate(self):
        await test_management.ManagementTests.setup_selected(self)
        return await self.client.post('/activate', json={'allowed_users': test_management.OWNER, 'confirm': True})

    async def test_foreign_webhook_receives_no_writes(self):
        self.hook = {'label': infrastructure.load()['webhook_label'], 'enabled': True, 'url': 'https://other.example.com', 'authorization': 'different'}
        response = await self.activate()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(settings.configured())
        self.assertFalse(any(c[1] == 'POST' for c in self.calls))
        self.restart_mock.assert_not_called()

    async def test_uncertain_remote_write_reconciles_only_owned_registration(self):
        provider = m.upstream.side_effect
        async def uncertain(token, method, path, **kwargs):
            result = await provider(token, method, path, **kwargs)
            if method == 'POST' and kwargs['payload'].get('enabled'):
                raise m.HTTPException(502, 'Timeout')
            return result
        with patch.object(m, 'upstream', side_effect=uncertain):
            response = await self.activate()
        self.assertEqual(response.status_code, 502)
        self.assertIs(self.hook['enabled'], False)
        self.assertFalse(settings.load()['hook_pending'])
        self.assertFalse(settings.configured())

    async def test_coolify_activation_pause_and_redeploy(self):
        self.restart_mock.return_value = False
        self.runtime_mock.return_value = False
        response = await self.activate()
        self.assertTrue(response.json()['redeploy_required'])
        self.assertFalse(response.json()['runtime_running'])
        self.runtime_mock.return_value = True
        self.assertTrue((await self.client.get('/state')).json()['runtime_running'])
        self.assertEqual((await self.client.post('/pause', json={})).status_code, 200)
        self.assertIs(self.hook['enabled'], False)

    async def test_oauth_owner_checked_on_server(self):
        config = infrastructure.validate({'owner_subject':'owner', 'owner_issuer':'https://issuer.example'})
        req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_required=True)),
                              state=SimpleNamespace(), method='GET')
        resp = SimpleNamespace(headers={})
        with patch.object(infrastructure, 'load', return_value=config):
            with self.assertRaises(m.HTTPException) as e:
                await m.protect(req, resp)
            self.assertEqual(e.exception.status_code, 401)
            req.state.session = SimpleNamespace(user_id='guest', issuer=config['owner_issuer'])
            with self.assertRaises(m.HTTPException) as e:
                await m.protect(req, resp)
            self.assertEqual(e.exception.status_code, 403)
            req.state.session.user_id = 'owner'
            await m.protect(req, resp)


class ReceiverTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_ports_and_instance_lease(self):
        import asyncio
        import socket
        from contextlib import ExitStack
        import httpx
        from gateway.config import PlatformConfig
        from ryzeapi.adapter import RyzeAdapter
        from ryzeapi.telemetry import EVENTS
        import test_ryzeapi

        async def idle(_adapter):
            await asyncio.Event().wait()

        with TemporaryDirectory() as directory, ExitStack() as stack:
            home = Path(directory)
            stack.enter_context(patch.object(settings, 'get_hermes_home', return_value=home))
            stack.enter_context(patch('ryzeapi.adapter.get_hermes_home', return_value=home))
            test_ryzeapi.module.register(SimpleNamespace(register_platform=lambda **kwargs: None))
            secret = 'synthetic-test-secret-' * 2
            url = 'https://hooks.example.com/ryzeapi/events'
            settings.save(dict(enabled=True, instance='hermes-test', instance_token='fixture',
                               webhook_secret=secret, allowed_users=test_management.OWNER,
                               hook_label='qa', hook_url=url))
            upstream = AsyncMock()
            upstream.envelope.return_value = {'webhooks': [dict(label='qa', url=url, enabled=True,
                authorization='Bearer '+secret, events=EVENTS, byEvents=False, mediaBase64=True)]}
            stack.enter_context(patch('ryzeapi.adapter.RyzeClient', return_value=upstream))
            for name in ('websocket_loop','monitor_connection','reconcile_receipts','consume'):
                stack.enter_context(patch.object(RyzeAdapter, name, idle))
            reserved = stack.enter_context(socket.socket())
            reserved.bind(('127.0.0.1', 9120))
            reserved.listen()
            first, second = RyzeAdapter(PlatformConfig()), RyzeAdapter(PlatformConfig())
            try:
                self.assertTrue(await first.connect())
                # Even a second profile choosing a different free port cannot receive the same instance.
                with patch.object(infrastructure, 'load', return_value=infrastructure.validate({'listener_port':9132})):
                    self.assertFalse(await second.connect())
                async with httpx.AsyncClient(base_url='http://127.0.0.1:9131', trust_env=False) as client:
                    self.assertEqual((await client.post('/ryzeapi/events',json={})).status_code,401)
                    response=await client.post('/ryzeapi/events',json={},headers={'Authorization':'Bearer '+secret})
                    self.assertEqual(response.status_code,200)
                await first.disconnect()
                self.assertTrue(await second.connect())
            finally:
                await first.disconnect()
                await second.disconnect()
