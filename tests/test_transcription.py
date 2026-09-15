import base64, unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import test_ryzeapi as original
from test_ryzeapi import norm,event,OWNER

class TranscriptionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=original.AdapterTests.asyncSetUp
    asyncTearDown=original.AdapterTests.asyncTearDown

    def item(self, mid, text='', kind=None):
        item=norm(event());item.update(id=mid,text=text)
        if kind: item['media']={'kind':kind,'mime':'audio/mpeg' if kind in {'ptt','audio'} else 'image/png',
                               'base64':base64.b64encode(b'synthetic-media').decode()}
        return item

    async def prepare(self, items):
        with patch('ryzeapi.adapter.get_hermes_home',return_value=Path(self.temp.name)):
            return await self.adapter.prepare_batch(items)

    async def test_transcripts_remain_between_texts_and_native_preparation_preserves_order(self):
        from gateway.run_inbound import GatewayInboundMixin
        self.adapter.transcribe_voice.side_effect=['AUDIO_ONE','AUDIO_TWO']
        e,echo=await self.prepare([self.item('1','FIRST'),self.item('2',kind='ptt'),self.item('3','MIDDLE'),
                                  self.item('4',kind='audio'),self.item('5','LAST')])
        ordered=['FIRST','AUDIO_ONE','MIDDLE','AUDIO_TWO','LAST']
        self.assertEqual([e.text.index(v) for v in ordered],sorted(e.text.index(v) for v in ordered))
        self.assertEqual(e.media_urls,[]);self.assertEqual(echo,[('AUDIO_ONE','2'),('AUDIO_TWO','4')])
        # Run the actual native preparation method: no mocked prepend behavior.
        native=GatewayInboundMixin()
        native._consume_pending_native_image_paths=lambda key: []
        native._prefix_inbound_sender_context=lambda event,source,text:text
        native._prepend_inbound_reply_context=lambda event,source,text:text
        native._enrich_inbound_voice=AsyncMock(side_effect=AssertionError('Duplicate STT'))
        prepared=await native._prepare_inbound_message_text(event=e,source=e.source,history=[],session_key='test')
        self.assertEqual(prepared,e.text)
        native._enrich_inbound_voice.assert_not_awaited()

    async def test_pending_merge_cannot_retranscribe_or_reorder_audio(self):
        from gateway.platforms.base import merge_pending_message_event
        from gateway.run_inbound import GatewayInboundMixin
        a,_=await self.prepare([self.item('1','FIRST'),self.item('2',kind='ptt')])
        b,_=await self.prepare([self.item('3','SECOND'),self.item('4',kind='image')])
        pending={'test':a};merge_pending_message_event(pending,'test',b,merge_text=True)
        self.assertLess(a.text.index('FIRST'),a.text.index('SECOND'))
        self.assertEqual(GatewayInboundMixin()._pending_event_audio_paths(a),[])
        self.assertEqual(len(a.media_urls),1)

    async def test_echo_off_keeps_transcript_for_ai_without_send(self):
        self.adapter.send=AsyncMock()
        with patch('ryzeapi.adapter.echo_transcripts',return_value=False):
            e,echo=await self.prepare([self.item('1',kind='ptt')])
            await self.adapter.send_transcripts(OWNER,echo)
        self.assertIn('Transcrição sintética',e.text)
        self.assertIn('Não publique',e.channel_prompt)
        self.adapter.send.assert_not_awaited()

    async def test_native_backend_fallback_and_empty_transcript(self):
        from ryzeapi.stt_worker import transcribe
        with patch('tools.transcription_tools.transcribe_audio',return_value={'success':False}), \
             patch('tools.transcription_tools.transcribe_audio_local_fallback',return_value={'success':True,'transcript':' recovered '}) as fallback:
            self.assertEqual(transcribe('/synthetic.mp3'),'recovered')
            fallback.assert_called_once()
        with patch('tools.transcription_tools.transcribe_audio',return_value={'success':True,'transcript':' '}):
            self.assertIsNone(transcribe('/synthetic.mp3'))

    async def test_echo_on_sends_each_in_order_even_identical_and_can_revoke_midway(self):
        from gateway.platforms.base import SendResult
        self.adapter.send=AsyncMock(return_value=SendResult(success=True))
        await self.adapter.send_transcripts(OWNER,[('same','a'),('same','b')])
        self.assertEqual([c.kwargs['reply_to'] for c in self.adapter.send.await_args_list],['a','b'])
        self.adapter.send.reset_mock()
        with patch('ryzeapi.adapter.echo_transcripts',side_effect=[True,False]):
            await self.adapter.send_transcripts(OWNER,[('one','a'),('two','b')])
        self.assertEqual(self.adapter.send.await_count,1)

    async def test_failure_keeps_slot_and_file_without_fabricated_echo(self):
        self.adapter.transcribe_voice.return_value=None
        e,echo=await self.prepare([self.item('1','FIRST'),self.item('2',kind='ptt'),self.item('3','LAST')])
        self.assertLess(e.text.index('FIRST'),e.text.index('Não foi possível'))
        self.assertLess(e.text.index('Não foi possível'),e.text.index('LAST'))
        self.assertIn('Arquivo de áudio original',e.text);self.assertEqual(echo,[])

    async def test_echo_still_obeys_firewall(self):
        self.adapter.client=AsyncMock()
        await self.adapter.send_transcripts('5511888888888',[('private','a')])
        self.adapter.client.send_text.assert_not_awaited()

    async def test_toggle_is_checked_between_fragments(self):
        self.adapter.client=AsyncMock()
        self.adapter.client.send_text.return_value='sent'
        with patch('ryzeapi.adapter.echo_transcripts',side_effect=[True,False]):
            await self.adapter.send(OWNER,'x'*8000,metadata={'ryze_transcript':True})
        self.assertEqual(self.adapter.client.send_text.await_count,1)
