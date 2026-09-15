"""Synthetic publication barriers; no restarts, model calls or WhatsApp sends."""
import asyncio, json, unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
import test_ryzeapi as original
from ryzeapi.deployment import native_activity, UpdateLease, safe_to_stop


class LeaseTests(unittest.TestCase):
    def test_owner_renewal_conflict_expiry_and_release(self):
        lease = UpdateLease()
        with patch('ryzeapi.deployment.time.monotonic', return_value=10):
            self.assertTrue(lease.acquire('one'))
            self.assertFalse(lease.acquire('two'))
            self.assertFalse(lease.release('two'))
            self.assertTrue(lease.acquire('one'))
        with patch('ryzeapi.deployment.time.monotonic', return_value=131):
            self.assertFalse(lease.active)
            self.assertTrue(lease.acquire('two'))
            self.assertTrue(lease.release('two'))
            self.assertFalse(lease.active)

    def test_unknown_and_busy_never_pass_stop_gate(self):
        healthy = dict(consumer_healthy=True, maintenance_active=True, active_batches=0, stt_busy=False,
            stt_waiting=0, ws_ingress_pending=0, ingest_pending=0, finalizations_pending=0,
            orphaned_preparations=0, native_activity=dict(known=True,agent_tasks=0,active_sessions=0,pending_messages=0))
        self.assertTrue(safe_to_stop(healthy))
        self.assertTrue(safe_to_stop(dict(healthy,buffer_pending=10)))  # durable behind barrier
        for key in healthy:
            missing = dict(healthy);missing.pop(key)
            self.assertFalse(safe_to_stop(missing), key)
        for key in ('agent_tasks','active_sessions','pending_messages'):
            self.assertFalse(safe_to_stop(dict(healthy,native_activity=dict(healthy['native_activity'],**{key:1}))))
        for value in (None, '0', -1, 1):
            self.assertFalse(safe_to_stop(dict(healthy,active_batches=value)))


class ActivityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = original.AdapterTests.asyncSetUp
    asyncTearDown = original.AdapterTests.asyncTearDown

    async def test_background_handoff_counted_after_inbox_admitted(self):
        task = asyncio.create_task(asyncio.Event().wait())
        try:
            self.adapter._background_tasks.add(task)
            self.adapter._session_tasks['private-session'] = task
            self.assertEqual(native_activity(self.adapter)['agent_tasks'],1)
            self.assertNotIn('private-session',json.dumps(native_activity(self.adapter)))
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertEqual(native_activity(self.adapter)['agent_tasks'],0)

    async def test_missing_native_contract_is_unknown(self):
        del self.adapter._session_tasks
        self.assertEqual(native_activity(self.adapter), {'known':False})

    async def test_pending_native_text_and_sessions_are_counted(self):
        self.adapter._pending_messages['one'] = object()
        self.adapter._text_debounce['two'] = SimpleNamespace(task=None)
        self.adapter._active_sessions['one'] = asyncio.Event()
        result = native_activity(self.adapter)
        self.assertEqual(result['pending_messages'],2)
        self.assertEqual(result['active_sessions'],1)

    async def test_maintenance_route_auth_validation_and_conflict(self):
        class Request:
            remote='127.0.0.1';headers={'Authorization':'Bearer '+'s'*40}
            json=AsyncMock(return_value={'action':'acquire','owner':'a'*64})
        request=Request()
        self.assertEqual((await self.adapter.maintenance(request)).status,200)
        request.json=AsyncMock(return_value={'action':'release','owner':'b'*64})
        self.assertEqual((await self.adapter.maintenance(request)).status,409)
        request.json=AsyncMock(return_value={'action':'acquire','owner':'bad'})
        self.assertEqual((await self.adapter.maintenance(request)).status,400)
        request.headers={}
        self.assertEqual((await self.adapter.maintenance(request)).status,401)

    async def test_barrier_keeps_messages_durable_then_resumes(self):
        from test_ryzeapi import norm,event
        self.adapter.inbox.put(norm(event()))
        self.adapter.update_lease.acquire('test')
        self.adapter._running=True
        received=asyncio.Event()
        async def handle(event):
            event._gateway_accepted=True;received.set()
        self.adapter.handle_message=handle
        worker=asyncio.create_task(self.adapter.consume())
        try:
            await asyncio.sleep(.35)
            self.assertFalse(received.is_set())
            self.assertEqual(self.adapter.inbox.db.execute("SELECT status FROM inbox").fetchone()[0],'pending')
            self.adapter.update_lease.release('test')
            await asyncio.wait_for(received.wait(),2)
        finally:
            worker.cancel();await asyncio.gather(worker,return_exceptions=True)

    async def test_barrier_does_not_cancel_existing_native_response(self):
        release=asyncio.Event();completed=asyncio.Event()
        async def respond():
            await release.wait();completed.set()
        task=asyncio.create_task(respond());self.adapter._background_tasks.add(task)
        try:
            self.adapter.update_lease.acquire('test')
            self.assertEqual(native_activity(self.adapter)['agent_tasks'],1)
            self.assertFalse(task.cancelled())
            release.set();await asyncio.wait_for(completed.wait(),1);await task
            self.assertEqual(native_activity(self.adapter)['agent_tasks'],0)
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_maintenance_rejects_non_loopback_even_with_secret(self):
        request=SimpleNamespace(remote='203.0.113.1',headers={'Authorization':'Bearer '+'s'*40},json=AsyncMock())
        self.assertEqual((await self.adapter.maintenance(request)).status,401)
        request.json.assert_not_awaited()
