"""One place to build the HTTP client every metadata source shares."""

import httpx

_USER_AGENT = "Mozilla/5.0 (compatible; larklab/0.1)"
_TIMEOUT_SECONDS = 15


def build_http_client(timeout: float = _TIMEOUT_SECONDS) -> httpx.Client:
    """Create a client that follows redirects and reuses connections.

    Callers own the client: use it as a context manager and pass it to the
    source functions so a batch of lookups shares one connection pool.
    """
    return httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
    )
