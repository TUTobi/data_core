"""Read Arduino rain values from USB serial and push them to data_core.

This program runs on the Windows computer connected to the Arduino.  It does
not expose the computer's COM port to Vercel; it sends HTTPS requests to the
existing data_core ingestion API instead.
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import re
import signal
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import serial
except ImportError:  # Gives a useful startup message if requirements were not installed.
    serial = None  # type: ignore[assignment]


LOG = logging.getLogger("rain_serial_bridge")
METRIC_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
DEFAULT_API_URL = "https://datacore-eta.vercel.app/v1/sensor-readings"


@dataclass(frozen=True)
class BridgeConfig:
    serial_port: str
    baudrate: int
    api_url: str
    api_key: str
    auth_disabled: bool
    sensor_id: str
    metric_name: str
    metric_unit: str | None
    lat: float | None
    lon: float | None
    request_timeout_s: float
    max_retries: int
    retry_initial_delay_s: float
    retry_max_delay_s: float
    serial_reconnect_delay_s: float
    queue_size: int

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        def optional_float(name: str) -> float | None:
            value = os.getenv(name, "").strip()
            return float(value) if value else None

        config = cls(
            serial_port=os.getenv("RAIN_SERIAL_PORT", "COM3").strip(),
            baudrate=int(os.getenv("RAIN_SERIAL_BAUD", "115200")),
            api_url=os.getenv("SENSOR_API_URL", DEFAULT_API_URL).strip(),
            api_key=os.getenv("SENSOR_API_KEY", "").strip(),
            auth_disabled=os.getenv("SENSOR_AUTH_DISABLED", "false").strip().lower() in {"1", "true", "yes"},
            sensor_id=os.getenv("RAIN_SENSOR_ID", "arduino-uno-r4-rain").strip(),
            metric_name=os.getenv("RAIN_METRIC_NAME", "rain_raw").strip(),
            metric_unit=os.getenv("RAIN_METRIC_UNIT", "adc").strip() or None,
            lat=optional_float("RAIN_SENSOR_LAT"),
            lon=optional_float("RAIN_SENSOR_LON"),
            request_timeout_s=float(os.getenv("RAIN_REQUEST_TIMEOUT_S", "30")),
            max_retries=int(os.getenv("RAIN_MAX_RETRIES", "5")),
            retry_initial_delay_s=float(os.getenv("RAIN_RETRY_INITIAL_DELAY_S", "2")),
            retry_max_delay_s=float(os.getenv("RAIN_RETRY_MAX_DELAY_S", "60")),
            serial_reconnect_delay_s=float(os.getenv("RAIN_SERIAL_RECONNECT_DELAY_S", "5")),
            queue_size=int(os.getenv("RAIN_QUEUE_SIZE", "1000")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.auth_disabled and not self.api_key:
            raise ValueError("SENSOR_API_KEY is required unless SENSOR_AUTH_DISABLED=true is explicitly set.")
        if not self.serial_port:
            raise ValueError("RAIN_SERIAL_PORT must not be empty.")
        if not self.api_url.startswith(("https://", "http://")):
            raise ValueError("SENSOR_API_URL must start with http:// or https://.")
        if not self.sensor_id or len(self.sensor_id) > 64:
            raise ValueError("RAIN_SENSOR_ID must contain 1 to 64 characters.")
        if not METRIC_RE.fullmatch(self.metric_name):
            raise ValueError("RAIN_METRIC_NAME must be a valid snake_case API metric name.")
        if (self.lat is None) != (self.lon is None):
            raise ValueError("RAIN_SENSOR_LAT and RAIN_SENSOR_LON must be configured together.")
        if self.lat is not None and not -90 <= self.lat <= 90:
            raise ValueError("RAIN_SENSOR_LAT must be between -90 and 90.")
        if self.lon is not None and not -180 <= self.lon <= 180:
            raise ValueError("RAIN_SENSOR_LON must be between -180 and 180.")
        if self.baudrate <= 0 or self.request_timeout_s <= 0 or self.queue_size <= 0:
            raise ValueError("Baud rate, request timeout, and queue size must be positive.")
        if self.max_retries < 0 or self.retry_initial_delay_s < 0 or self.retry_max_delay_s < 0:
            raise ValueError("Retry values must not be negative.")


def parse_rain_value(line: bytes | str) -> float | None:
    """Return the numeric ``rainValue`` in one complete Arduino JSON line.

    Arduino startup lines and malformed, incomplete, or non-numeric readings
    deliberately return ``None`` so they are never sent to the API.
    """
    try:
        text = line.decode("utf-8") if isinstance(line, bytes) else line
        body = json.loads(text.strip())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(body, dict):
        return None
    value = body.get("rainValue")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def reading_payload(config: BridgeConfig, rain_value: float, recorded_at: datetime | None = None) -> dict[str, Any]:
    """Map an Arduino raw value into the existing SensorReadingIn API model."""
    timestamp = recorded_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("recorded_at must be timezone-aware.")
    payload: dict[str, Any] = {
        "sensor_id": config.sensor_id,
        "recorded_at": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "metrics": {config.metric_name: rain_value},
    }
    if config.metric_unit:
        payload["units"] = {config.metric_name: config.metric_unit}
    if config.lat is not None:
        payload["lat"] = config.lat
        payload["lon"] = config.lon
    return payload


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    body: str


class NetworkError(RuntimeError):
    pass


class ApiClient(Protocol):
    def post(self, payload: dict[str, Any]) -> ApiResponse: ...


class SensorApiClient:
    """Small standard-library HTTP client for the existing sensor endpoint."""

    def __init__(self, config: BridgeConfig, opener: Callable[..., Any] = urlopen):
        self._url = config.api_url
        self._api_key = config.api_key
        self._timeout_s = config.request_timeout_s
        self._opener = opener

    def post(self, payload: dict[str, Any]) -> ApiResponse:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        request = Request(
            self._url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout_s) as response:
                return ApiResponse(response.status, response.read().decode("utf-8", errors="replace"))
        except HTTPError as exc:
            return ApiResponse(exc.code, exc.read().decode("utf-8", errors="replace"))
        except (URLError, OSError, TimeoutError) as exc:
            raise NetworkError(str(exc)) from exc


def _is_retryable_status(status_code: int) -> bool:
    # 409 is explicitly retryable in the service contract. 429 is also temporary.
    return status_code == 409 or status_code == 429 or 500 <= status_code <= 599


def send_with_retries(
    client: ApiClient,
    payload: dict[str, Any],
    *,
    max_retries: int,
    initial_delay_s: float,
    max_delay_s: float,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Send one value; retry only temporary network/API failures a finite number of times."""
    value = next(iter(payload["metrics"].values()))
    for attempt in range(max_retries + 1):
        retry_reason: str | None = None
        try:
            response = client.post(payload)
            if 200 <= response.status_code < 300:
                LOG.info("rainValue=%s sent; HTTP %s", value, response.status_code)
                return True
            if _is_retryable_status(response.status_code):
                retry_reason = f"HTTP {response.status_code}: {response.body[:300]}"
            else:
                LOG.error("rainValue=%s rejected; HTTP %s: %s", value, response.status_code, response.body[:300])
                return False
        except NetworkError as exc:
            retry_reason = f"network error: {exc}"

        if attempt == max_retries:
            LOG.error("rainValue=%s not sent after %s attempt(s): %s", value, attempt + 1, retry_reason)
            return False
        delay = min(initial_delay_s * (2**attempt), max_delay_s)
        LOG.warning(
            "rainValue=%s temporary delivery failure (%s); retrying in %.1f s (%s/%s)",
            value,
            retry_reason,
            delay,
            attempt + 1,
            max_retries,
        )
        sleep(delay)
    return False  # Unreachable, keeps type checkers satisfied.


class RainSerialBridge:
    def __init__(self, config: BridgeConfig, client: ApiClient | None = None):
        self.config = config
        self.client = client or SensorApiClient(config)
        self.stop_event = threading.Event()
        self._readings: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=config.queue_size)
        self._uploader = threading.Thread(target=self._upload_loop, name="rain-api-uploader", daemon=True)

    def request_stop(self, *_: object) -> None:
        LOG.info("Stop requested; closing the serial connection.")
        self.stop_event.set()

    def _upload_loop(self) -> None:
        while not self.stop_event.is_set() or not self._readings.empty():
            try:
                payload = self._readings.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                send_with_retries(
                    self.client,
                    payload,
                    max_retries=self.config.max_retries,
                    initial_delay_s=self.config.retry_initial_delay_s,
                    max_delay_s=self.config.retry_max_delay_s,
                    sleep=self.stop_event.wait,
                )
            finally:
                self._readings.task_done()

    def _handle_line(self, line: bytes) -> None:
        rain_value = parse_rain_value(line)
        if rain_value is None:
            LOG.warning("Ignoring invalid or incomplete serial line: %r", line[:200])
            return
        payload = reading_payload(self.config, rain_value)
        try:
            self._readings.put(payload, timeout=0.1)
            LOG.info("rainValue=%s read from %s; queued for upload", rain_value, self.config.serial_port)
        except queue.Full:
            LOG.error("Upload queue is full; dropping rainValue=%s", rain_value)

    def run_forever(self) -> None:
        if serial is None:
            raise RuntimeError("pyserial is not installed. Run: py -m pip install -r sensor_bridge/requirements.txt")
        self._uploader.start()
        while not self.stop_event.is_set():
            try:
                # timeout makes readline return periodically, so Ctrl+C/stop closes promptly.
                with serial.Serial(self.config.serial_port, self.config.baudrate, timeout=1) as connection:
                    LOG.info("Opened %s at %s baud", self.config.serial_port, self.config.baudrate)
                    while not self.stop_event.is_set():
                        line = connection.readline()
                        if line:
                            self._handle_line(line)
            except serial.SerialException as exc:
                LOG.error("Cannot use %s: %s; retrying in %.1f s", self.config.serial_port, exc, self.config.serial_reconnect_delay_s)
                self.stop_event.wait(self.config.serial_reconnect_delay_s)
            finally:
                LOG.info("Serial connection closed.")
        self._uploader.join(timeout=self.config.request_timeout_s + 1)


def main() -> int:
    logging.basicConfig(level=os.getenv("RAIN_LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")
    try:
        bridge = RainSerialBridge(BridgeConfig.from_env())
    except (ValueError, TypeError) as exc:
        LOG.error("Invalid configuration: %s", exc)
        return 2

    signal.signal(signal.SIGINT, bridge.request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, bridge.request_stop)
    try:
        bridge.run_forever()
    except KeyboardInterrupt:
        bridge.request_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
