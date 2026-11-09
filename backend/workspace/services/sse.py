"""Server-sent events for the chat stream, under WSGI and ASGI.

There is one producer, a generator of (event, data) pairs. Under WSGI (and
Django's test client) the response iterates it inline. Under ASGI (Daphne)
Django would consume a *sync* iterator with `sync_to_async(list)` — buffering
the whole answer and sending it at the end, which is exactly what streaming
is meant to avoid. So there the view returns an async iterator instead: the
producer runs in a worker thread and hands each frame to the event loop with
`loop.call_soon_threadsafe` into an `asyncio.Queue`.

The worker thread is not tied to the client: if the browser disconnects, the
async side stops reading but the producer keeps going, so the finished answer
is still persisted and shows up on reload.
"""
import asyncio
import json
import logging
import threading

from django.core.handlers.asgi import ASGIRequest
from django.db import connections
from django.http import StreamingHttpResponse
from rest_framework.utils.encoders import JSONEncoder

logger = logging.getLogger(__name__)

PING = b": ping\n\n"
PING_INTERVAL_SECONDS = 15.0
_DONE = object()
INTERNAL_ERROR = {
    "error": {
        "code": "internal_error", "message": "The answer could not be completed. Try again.",
        "retryable": True, "stage": None, "details": None,
    },
    "message": None,
}


def format_event(name, data):
    payload = json.dumps(data, cls=JSONEncoder, ensure_ascii=False, separators=(",", ":"))
    return f"event: {name}\ndata: {payload}\n\n".encode("utf-8")


def sync_stream(producer_factory):
    """Frames for WSGI and the test client: the producer runs in this thread."""
    producer = producer_factory()
    try:
        for name, data in producer:
            yield format_event(name, data)
    except Exception:
        logger.exception("Chat stream producer failed")
        yield format_event("error", INTERNAL_ERROR)
    finally:
        # On a client disconnect the server closes this generator; closing the
        # producer lets it record that the answer was cut short.
        producer.close()


async def async_stream(producer_factory, ping_interval=PING_INTERVAL_SECONDS):
    """Frames for ASGI: the producer runs in a worker thread (see module doc)."""
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    consumer_gone = threading.Event()

    def push(item):
        if consumer_gone.is_set():
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:
            # The event loop has closed (server shutdown). Keep producing so
            # the answer is still saved; there is just nobody to send it to.
            consumer_gone.set()

    def work():
        try:
            for name, data in producer_factory():
                push(format_event(name, data))
        except Exception:
            logger.exception("Chat stream producer failed")
            push(format_event("error", INTERNAL_ERROR))
        finally:
            # This thread opened its own database connections; nothing else
            # will ever close them.
            connections.close_all()
            push(_DONE)

    threading.Thread(target=work, name="chat-stream-producer", daemon=True).start()
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=ping_interval)
            except asyncio.TimeoutError:
                yield PING  # keeps proxies from closing an idle connection
                continue
            if item is _DONE:
                return
            yield item
    finally:
        consumer_gone.set()


def is_asgi(request):
    return isinstance(getattr(request, "_request", request), ASGIRequest)


def event_stream_response(request, producer_factory):
    if is_asgi(request):
        content = async_stream(producer_factory)
    else:
        content = sync_stream(producer_factory)
    response = StreamingHttpResponse(content, content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    # nginx buffers proxied responses by default, which would hold every
    # token back until the answer is complete.
    response["X-Accel-Buffering"] = "no"
    return response
