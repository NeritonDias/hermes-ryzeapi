"""Read-only native activity and an expiring, process-local publication barrier."""
import time


def native_activity(adapter):
    """Count native handoffs even after our durable inbox says 'admitted'. No IDs."""
    try:
        maps = [getattr(adapter, name) for name in (
            '_active_sessions', '_pending_messages', '_pending_text_batches',
            '_pending_text_batch_tasks', '_session_tasks', '_text_debounce')]
        background = adapter._background_tasks
        if not all(isinstance(value, dict) for value in maps) or not isinstance(background, set):
            raise TypeError('Native activity contract changed')
        sessions, pending, batches, batch_tasks, session_tasks, debounce = maps
        tasks = set(background) | set(batch_tasks.values()) | set(session_tasks.values())
        tasks.update(state.task for state in debounce.values() if state.task is not None)
        return {'known': True, 'agent_tasks': sum(not task.done() for task in tasks),
                'active_sessions': len(sessions), 'pending_messages': len(pending)+len(batches)+len(debounce)}
    except (AttributeError, TypeError):
        return {'known': False}


class UpdateLease:
    """Stops new preparations, not inbound persistence or existing agent replies."""
    TTL = 120

    def __init__(self):
        self.owner = None
        self.deadline = 0

    @property
    def active(self):
        return self.owner is not None and time.monotonic() < self.deadline

    def acquire(self, owner):
        if self.active and self.owner != owner:
            return False
        self.owner, self.deadline = owner, time.monotonic()+self.TTL
        return True

    def release(self, owner):
        if self.active and self.owner != owner:
            return False
        self.owner, self.deadline = None, 0
        return True


def safe_to_stop(health):
    activity = health.get('native_activity') or {}
    required = ('active_batches', 'stt_busy', 'stt_waiting', 'ws_ingress_pending',
                'ingest_pending', 'finalizations_pending', 'orphaned_preparations')
    native = ('agent_tasks', 'active_sessions', 'pending_messages')
    # Missing/invalid counters are unknown, never an idle zero. Pending inbox rows
    # are durable and deliberately remain pending behind the publication barrier.
    zero = lambda value: type(value) in (int, bool) and value == 0
    return (health.get('consumer_healthy') is True and health.get('maintenance_active') is True
            and activity.get('known') is True
            and all(zero(health.get(key)) for key in required)
            and all(zero(activity.get(key)) for key in native))
