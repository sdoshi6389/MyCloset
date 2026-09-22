import threading

import httpx
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

# One shared client for the whole process.
#
# This was previously threading.local(), but Flask serves each request on a new
# thread, so the cache never hit: every request paid a fresh create_client()
# (~390 ms) plus a cold TLS handshake (~550 ms). Reusing one client keeps the
# underlying httpx connection pool warm — a query drops from ~940 ms to ~110 ms.
# The sync client is thread-safe; httpx serialises access to its pool.
_client: Client | None = None
_lock = threading.Lock()


class _ResilientTransport(httpx.HTTPTransport):
    """Retry once when the server closed a pooled connection before answering.

    A long-lived pool will occasionally hand out a keep-alive connection that
    Supabase has already dropped — the request then fails with
    RemoteProtocolError("Server disconnected"). That became reachable once the
    client was shared, because a request thread can sit idle (e.g. behind the
    CLIP model load) while its connection goes stale.

    Only methods that are safe to repeat are retried: a dropped connection
    cannot tell us whether the server had already applied a write, so POST /
    PATCH / DELETE are surfaced to the caller rather than risk duplicating an
    insert. The retry runs on a fresh connection because the dead one is
    discarded when it errors.
    """

    _REPLAYABLE = frozenset({"GET", "HEAD", "OPTIONS"})

    def handle_request(self, request):
        try:
            return super().handle_request(request)
        except (httpx.RemoteProtocolError, httpx.ConnectError) as exc:
            if request.method.upper() not in self._REPLAYABLE:
                raise
            print(f"↻ Supabase {request.method} retried after: {type(exc).__name__}")
            return super().handle_request(request)


def _harden(client: Client) -> Client:
    """Swap in the retrying transport on each sub-client's httpx session."""
    for holder in (getattr(client, "postgrest", None), getattr(client, "storage", None)):
        session = getattr(holder, "session", None)
        if isinstance(session, httpx.Client):
            try:
                session._transport = _ResilientTransport()
            except Exception as e:
                print(f"⚠️  Could not harden Supabase transport: {e}")
    return client


def get_supa() -> Client:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = _harden(create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY))
    return _client


get_db = get_supa
