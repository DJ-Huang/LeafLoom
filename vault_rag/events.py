"""Bounded, process-local change notifications; clients reset after gaps/reconnects."""
from __future__ import annotations

from collections import deque
import asyncio
import contextlib
import threading
import uuid


class Changes:
    def __init__(self):
        self.instance = uuid.uuid4().hex
        self.condition = threading.Condition()
        self.sequence = 0
        self.messages = deque(maxlen=64)
        self.closed = False
        self.listeners = {}

    def publish(self, kind, **value):
        with self.condition:
            self.sequence += 1
            message = {'type': kind, 'sequence': self.sequence,
                       'service_instance_id': self.instance, **value}
            self.messages.append(message)
            self.condition.notify_all()
            for queue, loop in list(self.listeners.items()):
                if not loop.is_closed():loop.call_soon_threadsafe(self._deliver, queue, message)
            return message

    @staticmethod
    def _deliver(queue, message):
        if queue.full():
            while not queue.empty():queue.get_nowait()
            if message is not None:
                message={'type':'reset','sequence':message['sequence'],'service_instance_id':message['service_instance_id']}
        queue.put_nowait(message)

    @contextlib.asynccontextmanager
    async def listen(self):
        # SSE waits stay on the event loop, never occupy the foreground I/O pool.
        queue=asyncio.Queue(maxsize=64);loop=asyncio.get_running_loop()
        with self.condition:
            self.listeners[queue]=loop;sequence=self.sequence
        try:yield queue, sequence
        finally:
            with self.condition:self.listeners.pop(queue,None)

    def wait(self, after, timeout=15):
        with self.condition:
            self.condition.wait_for(lambda: self.closed or self.sequence > after, timeout)
            if self.closed or self.sequence <= after:
                return []
            if self.messages and after < self.messages[0]['sequence'] - 1:
                return [{'type': 'reset', 'sequence': self.sequence,
                         'service_instance_id': self.instance}]
            return [message for message in self.messages if message['sequence'] > after]

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
            for queue,loop in list(self.listeners.items()):
                if not loop.is_closed():loop.call_soon_threadsafe(self._deliver,queue,None)
