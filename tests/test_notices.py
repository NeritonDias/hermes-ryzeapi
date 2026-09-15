"""Plugin-only suppression; real native notice path, no external messages."""
import unittest
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import test_ryzeapi as original
from test_ryzeapi import OWNER
from ryzeapi.groups import GroupStore
from pathlib import Path

GID='120363000000000001@g.us'

class NoticeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await original.AdapterTests.asyncSetUp(self)
        self.adapter.client=AsyncMock()
        self.adapter.client.send_text.return_value='sent-test-notice'
        self.adapter.group_store=GroupStore(Path(self.temp.name)/'groups','hermes-test')
        self.adapter.group_store.sync([{'groupJid':GID,'name':'Synthetic'}])
        self.adapter.group_store.configure(GID,'respond','mentions','all')

    async def asyncTearDown(self):
        self.adapter.group_store.close()
        await original.AdapterTests.asyncTearDown(self)

    async def test_setup_notice_suppressed_without_send_or_timing(self):
        self.adapter.observe_response=AsyncMock()
        for destination in (OWNER,GID):
            result=await self.adapter.send(destination,self.adapter.HOME_CHANNEL_SETUP_NOTICE)
            self.assertTrue(result.success)
            self.assertIsNone(result.message_id)
        self.adapter.client.send_text.assert_not_awaited()
        self.adapter.observe_response.assert_not_called()
        self.assertIsNone(self.adapter.last_send_at)
        self.assertEqual(self.adapter.stats['sent_text'],0)
        self.assertEqual(self.adapter.stats['home_setup_notice_suppressed'],2)
        self.assertIsNone(self.adapter.config.home_channel)

    async def test_other_notices_responses_and_quoted_text_are_preserved(self):
        for content in ('Olá!','Falha ao executar tarefa.',
                        'Home channel configured.','Use /sethome para configurar.',
                        'Texto citado: '+self.adapter.HOME_CHANNEL_SETUP_NOTICE):
            self.assertTrue((await self.adapter.send(GID,content)).success)
        self.assertEqual(self.adapter.client.send_text.await_count,5)
        self.assertEqual(self.adapter.stats['home_setup_notice_suppressed'],0)

    async def test_suppression_does_not_bypass_firewall_or_pause(self):
        self.adapter.group_store.configure(GID,'listen','mentions','all')
        for destination in (GID,'5511777777777'):
            self.assertFalse((await self.adapter.send(destination,self.adapter.HOME_CHANNEL_SETUP_NOTICE)).success)
        with patch('ryzeapi.adapter.load',return_value={'enabled':False}):
            self.assertFalse((await self.adapter.send(OWNER,self.adapter.HOME_CHANNEL_SETUP_NOTICE)).success)
        self.adapter.client.send_text.assert_not_awaited()
        self.assertEqual(self.adapter.stats['home_setup_notice_suppressed'],0)

    async def test_native_first_contact_path_then_normal_response(self):
        from gateway.run_turn import GatewayTurnMixin
        from gateway.run_notifications import GatewayNotificationsMixin
        config=SimpleNamespace(get_home_channel=lambda p:None,
                               get_notice_delivery=lambda p:'public')
        runner=SimpleNamespace(config=config,
            async_session_store=SimpleNamespace(has_any_sessions=AsyncMock(return_value=True)),
            _adapter_for_source=lambda source:self.adapter,
            _thread_metadata_for_source=lambda source:None)
        runner._deliver_platform_notice=partial(GatewayNotificationsMixin._deliver_platform_notice,runner)
        for destination,kind in ((GID,'group'),(OWNER,'dm')):
            source=SimpleNamespace(platform=self.adapter.platform,chat_id=destination,
                chat_type=kind,user_id=OWNER,profile='default')
            with patch('gateway.run._home_target_env_var',return_value=None):
                await GatewayTurnMixin._hmwa_first_contact_notes(runner,source,[],[])
        self.adapter.client.send_text.assert_not_awaited()
        self.assertEqual(self.adapter.stats['home_setup_notice_suppressed'],2)
        self.assertIsNone(self.adapter.config.home_channel)
        self.assertTrue((await self.adapter.send(GID,'Oi, como posso ajudar?')).success)
        self.adapter.client.send_text.assert_awaited_once_with(GID,'Oi, como posso ajudar?',None)
