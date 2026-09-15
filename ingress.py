"""Bounded WS scheduling. Same raw/canonical contact is FIFO, different lanes run independently."""
import asyncio
from collections import deque

class LaneQueue:
    def __init__(self, handler, key, *, workers=4, max_items=100, max_bytes=50*1024*1024):
        self.handler, self.key = handler,key
        self.worker_count,self.max_items,self.max_bytes = workers,max_items,max_bytes
        self.items = deque(); self.active = set(); self.bytes = 0; self.count = 0
        self.processing = {}
        self.wake = asyncio.Event(); self.tasks = []

    def start(self):
        if not self.tasks:
            self.tasks = [asyncio.create_task(self.work(),name='ryzeapi-ws-ingress') for _ in range(self.worker_count)]

    def put(self,payload,size,completion=None,*,control=False):
        reserve = bool(control and size<=1600)
        if self.count>=self.max_items+(10 if reserve else 0) or self.bytes+size>self.max_bytes+(16000 if reserve else 0): return False
        self.items.append((self.key(payload),payload,size,completion))
        self.count+=1;self.bytes+=size;self.wake.set()
        return True

    async def work(self):
        while True:
            picked = next((i for i,item in enumerate(self.items) if item[0] not in self.active),None)
            if picked is None:
                self.wake.clear()
                await self.wake.wait()
                continue
            key,payload,size,completion = self.items[picked]; del self.items[picked]
            self.active.add(key)
            self.processing[key] = payload
            try:
                result = await self.handler(payload)
                if completion is not None and not completion.done(): completion.set_result(result)
            finally:
                if completion is not None and not completion.done(): completion.set_result('retry')
                self.active.remove(key);self.processing.pop(key,None);self.count-=1;self.bytes-=size;self.wake.set()

    def pending_payloads(self):
        return [item[1] for item in self.items]+list(self.processing.values())

    async def close(self):
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        for _,_,_,completion in self.items:
            if completion is not None and not completion.done(): completion.set_result('retry')
        self.tasks.clear();self.items.clear();self.count=0;self.bytes=0
