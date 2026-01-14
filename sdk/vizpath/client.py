"""HTTP client for sending traces to the vizpath server."""

import atexit
import logging
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import List, Optional

import httpx

from vizpath.config import Config
from vizpath.exceptions import (
    AuthenticationError,
    ConnectionError,
    RateLimitError,
    TimeoutError,
    VizpathError,
)
from vizpath.span import SpanData

logger = logging.getLogger(__name__)


class Client:
    """
    Async-buffered HTTP client for trace ingestion.

    Collects spans in a buffer and flushes them periodically or when
    the buffer is full. Uses a background thread for non-blocking sends.
    """

    _instances: List["Client"] = []

    def __init__(self, config: Config) -> None:
        self._config = config
        self._buffer: Queue[SpanData] = Queue()
        self._lock = Lock()
        self._shutdown = Event()
        self._client: Optional[httpx.Client] = None
        self._flush_thread: Optional[Thread] = None

        if config.enabled and config.api_key:
            self._initialize()
            Client._instances.append(self)

    def _initialize(self) -> None:
        """Initialize HTTP client and background flush thread."""
        self._client = httpx.Client(
            base_url=self._config.base_url,
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self._config.timeout,
        )

        self._flush_thread = Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        """Background loop that flushes buffer periodically."""
        while not self._shutdown.wait(self._config.flush_interval):
            self._flush()

    def send(self, span: SpanData) -> None:
        """Add a span to the send buffer."""
        if not self._config.enabled:
            return

        self._buffer.put(span)

        if self._buffer.qsize() >= self._config.buffer_size:
            self._flush()

    def _flush(self) -> None:
        """Flush all buffered spans to the server."""
        if not self._client:
            return

        spans: List[SpanData] = []
        while True:
            try:
                spans.append(self._buffer.get_nowait())
            except Empty:
                break

        if not spans:
            return

        try:
            payload = [s.model_dump(mode="json") for s in spans]
            response = self._client.post("/traces/spans/batch", json=payload)
            self._handle_response(response)
            logger.debug(f"Flushed {len(spans)} spans")
        except httpx.ConnectError as e:
            logger.warning(f"Connection failed, re-buffering {len(spans)} spans: {e}")
            for span in spans:
                self._buffer.put(span)
        except httpx.TimeoutException as e:
            logger.warning(f"Request timeout, re-buffering {len(spans)} spans: {e}")
            for span in spans:
                self._buffer.put(span)
        except VizpathError as e:
            logger.error(f"API error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during flush: {e}")

    def _handle_response(self, response: httpx.Response) -> None:
        """Handle HTTP response and raise appropriate exceptions."""
        if response.status_code == 401:
            raise AuthenticationError("Invalid API key")
        if response.status_code == 429:
            raise RateLimitError("Rate limit exceeded")
        if response.status_code >= 500:
            raise ConnectionError(f"Server error: {response.status_code}")
        if not response.is_success:
            raise VizpathError(f"Request failed: {response.status_code} {response.text}")

    def close(self) -> None:
        """Shutdown the client and flush remaining spans."""
        self._shutdown.set()

        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=2.0)

        self._flush()

        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


@atexit.register
def _cleanup() -> None:
    """Ensure all clients flush on interpreter shutdown."""
    for client in Client._instances:
        try:
            client.close()
        except Exception:
            pass
