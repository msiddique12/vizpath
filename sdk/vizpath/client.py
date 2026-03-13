"""HTTP client for sending traces to the vizpath server."""

from __future__ import annotations

import atexit
import json
import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from typing import Any

import httpx

from vizpath.config import Config
from vizpath.exceptions import (
    AuthenticationError,
    ConnectionError,
    RateLimitError,
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

    _instances: list[Client] = []

    def __init__(self, config: Config) -> None:
        self._config = config
        self._buffer: Queue[SpanData] = Queue(maxsize=self._config.max_buffer_items)
        self._lock = Lock()
        self._shutdown = Event()
        self._client: httpx.Client | None = None
        self._flush_thread: Thread | None = None
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0
        self._dropped_spans = 0
        self._flushed_spans = 0
        self._flush_failures = 0

        if config.enabled:
            self._initialize()
            Client._instances.append(self)

    def _initialize(self) -> None:
        """Initialize HTTP client and background flush thread."""
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["X-API-Key"] = self._config.api_key
            logger.info("Vizpath client initialized with API key authentication")
        else:
            logger.info("Vizpath client initialized without API key (local dev mode)")

        self._client = httpx.Client(
            base_url=self._config.base_url,
            headers=headers,
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

        with self._lock:
            if self._buffer.full():
                if self._config.drop_oldest_when_full:
                    try:
                        self._buffer.get_nowait()
                        self._dropped_spans += 1
                        logger.warning(
                            "Trace buffer full, dropping oldest span to make room for new span"
                        )
                    except Empty:
                        pass
                    else:
                        self._buffer.put_nowait(span)
                        return
                logger.warning(
                    "Trace buffer full, dropping newest span"
                )
                self._dropped_spans += 1
                return
            self._buffer.put_nowait(span)

        if self._buffer.qsize() >= self._config.buffer_size:
            self._flush()

    def _flush(self) -> None:
        """Flush all buffered spans to the server."""
        if not self._client:
            return
        if self._is_circuit_open():
            return

        spans: list[SpanData] = []
        with self._lock:
            while True:
                try:
                    spans.append(self._buffer.get_nowait())
                except Empty:
                    break

        if not spans:
            return

        self._send_with_retry(spans)

    def flush(self) -> None:
        """Flush any queued spans immediately."""
        self._flush()

    def _send_with_retry(self, spans: list[SpanData]) -> None:
        """Send spans with exponential backoff retry."""
        payload_batches = self._chunk_payloads(spans)

        for index, (batch_payload, batch_spans) in enumerate(payload_batches):
            if self._send_payload_with_retry(batch_payload, batch_spans):
                continue

            # Keep order by re-buffering current and remaining spans.
            for _, remaining_spans in payload_batches[index + 1 :]:
                self._rebuffer_spans(remaining_spans)
            return

    def _send_payload_with_retry(self, payload: list[dict], spans: list[SpanData]) -> bool:
        """Send one payload batch with retry. Returns True only if the batch succeeded."""
        last_error: Exception | None = None
        saw_transport_error = False

        for attempt in range(self._config.max_retries):
            try:
                response = self._client.post("/traces/spans/batch", json=payload)
                self._handle_response(response)
                self._flushed_spans += len(spans)
                logger.debug(f"Flushed {len(spans)} spans")
                self._record_transport_success()
                return True
            except (httpx.ConnectError, httpx.TimeoutException, ConnectionError) as e:
                last_error = e
                saw_transport_error = True
                if attempt < self._config.max_retries - 1:
                    wait_time = (2 ** attempt) * 0.1  # 0.1s, 0.2s, 0.4s...
                    logger.debug(f"Retry {attempt + 1}/{self._config.max_retries} in {wait_time}s")
                    time.sleep(wait_time)
            except RateLimitError as e:
                last_error = e
                if attempt < self._config.max_retries - 1:
                    wait_time = e.retry_after if e.retry_after is not None else (2 ** attempt) * 1.0
                    # Longer wait for rate limits.
                    logger.warning(f"Rate limited, retry in {wait_time}s")
                    time.sleep(wait_time)
            except VizpathError as e:
                logger.error(f"API error: {e}")
                self._rebuffer_spans(spans)
                return False
            except Exception as e:
                logger.error(f"Unexpected error during flush: {e}")
                self._rebuffer_spans(spans)
                return False

        if saw_transport_error:
            self._record_transport_failure()
            self._flush_failures += 1
        logger.warning(f"All retries failed, re-buffering {len(spans)} spans: {last_error}")
        self._rebuffer_spans(spans)
        return False

    def _chunk_payloads(self, spans: list[SpanData]) -> list[tuple[list[dict], list[SpanData]]]:
        """Split spans into payload batches that satisfy the configured byte limit."""
        if not spans:
            return []

        if self._config.max_payload_bytes <= 0:
            payload = [self._sanitize_payload(span.model_dump(mode="json")) for span in spans]
            return [(payload, spans)]

        payload = [self._sanitize_payload(span.model_dump(mode="json")) for span in spans]
        batches: list[tuple[list[dict], list[SpanData]]] = []
        batch_payload: list[dict] = []
        batch_spans: list[SpanData] = []

        for span_payload, span in zip(payload, spans):
            candidate = batch_payload + [span_payload]
            candidate_bytes = len(json.dumps(candidate).encode("utf-8"))

            if batch_payload and candidate_bytes > self._config.max_payload_bytes:
                batches.append((batch_payload, batch_spans))
                batch_payload = [span_payload]
                batch_spans = [span]
                continue

            batch_payload = candidate
            batch_spans.append(span)

        if batch_payload:
            batches.append((batch_payload, batch_spans))

        return batches

    def _rebuffer_spans(self, spans: list[SpanData]) -> None:
        """Re-buffer spans when a send attempt fails."""
        for span in spans:
            try:
                self._buffer.put_nowait(span)
            except Full:
                self._dropped_spans += 1

    def _is_circuit_open(self) -> bool:
        """Return True if the client is in a temporary transport outage backoff."""
        if not self._config.circuit_breaker_enabled:
            return False

        if self._consecutive_failures < self._config.circuit_breaker_failures:
            return False

        return time.time() < self._circuit_open_until

    def _record_transport_failure(self) -> None:
        """Track consecutive transport failures and open a backoff window."""
        if self._is_circuit_open():
            return

        self._consecutive_failures += 1
        if self._consecutive_failures < self._config.circuit_breaker_failures:
            return

        # Keep the counter capped at threshold while backoff is open.
        self._consecutive_failures = self._config.circuit_breaker_failures
        self._circuit_open_until = time.time() + self._config.circuit_breaker_window_seconds
        logger.warning(
            "Transport failures exceeded threshold, entering cooldown for %s seconds",
            self._config.circuit_breaker_window_seconds,
        )

    def _record_transport_success(self) -> None:
        """Reset transport failure state after a successful send."""
        if self._consecutive_failures > 0:
            self._consecutive_failures = 0
            self._circuit_open_until = 0.0

    def _handle_response(self, response: httpx.Response) -> None:
        """Handle HTTP response and raise appropriate exceptions."""
        if response.status_code == 401:
            raise AuthenticationError("Invalid API key")
        if response.status_code == 429:
            raw_retry_after = response.headers.get("Retry-After")
            retry_after: float | None = None
            if raw_retry_after is not None:
                try:
                    retry_after = float(raw_retry_after)
                except (TypeError, ValueError):
                    try:
                        retry_dt = parsedate_to_datetime(raw_retry_after)
                        if retry_dt is not None:
                            now = datetime.now(timezone.utc)
                            retry_after = max(0.0, (retry_dt - now).total_seconds())
                    except (TypeError, ValueError, OverflowError):
                        retry_after = None

            raise RateLimitError("Rate limit exceeded", retry_after=retry_after)
        if response.status_code >= 500:
            raise ConnectionError(f"Server error: {response.status_code}")
        if not response.is_success:
            raise VizpathError(f"Request failed: {response.status_code} {response.text}")

    def _sanitize_payload(self, value: Any) -> Any:
        """Redact configured sensitive values from payload recursively."""
        if not self._config.redaction_enabled:
            return value

        sensitive = {field.lower() for field in self._config.redaction_fields}
        replacement = self._config.redaction_replacement

        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, nested in value.items():
                if isinstance(key, str) and key.lower() in sensitive:
                    redacted[key] = replacement
                else:
                    redacted[key] = self._sanitize_payload(nested)
            return redacted

        if isinstance(value, list):
            return [self._sanitize_payload(item) for item in value]

        if isinstance(value, tuple):
            return tuple(self._sanitize_payload(item) for item in value)

        return value

    def close(self) -> None:
        """Shutdown the client and flush remaining spans."""
        if self._shutdown.is_set():
            return

        self._shutdown.set()

        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=2.0)

        self.flush()

        if self._client:
            self._client.close()
            self._client = None

    def stats(self) -> dict[str, int]:
        """Return client runtime metrics."""
        return {
            "buffered": self._buffer.qsize(),
            "dropped_spans": self._dropped_spans,
            "flushed_spans": self._flushed_spans,
            "flush_failures": self._flush_failures,
        }

    def __enter__(self) -> Client:
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
