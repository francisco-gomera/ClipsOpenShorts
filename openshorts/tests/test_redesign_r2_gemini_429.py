"""
Rediseño R2 — Gemini 429 / Rate Limiting & Error Classification
================================================================
Verifica el tratamiento de errores 429 de Gemini:
  1. parse_retry_delay_from_exception:
     - Header HTTP Retry-After (segundos enteros, decimales, case-insensitive)
     - Header HTTP Retry-After (formato HTTP-date)
     - Detalles RPC estructurados (google.rpc.RetryInfo dict con retryDelay / retry_delay)
     - Detalles RPC con objeto protobuf simulado (seconds + nanos)
     - Metadata gRPC [("retry-after", "...")]
     - Fallback regex sobre str(exc)
  2. is_rate_limit:
     - Status code 429 (int/str), RESOURCE_EXHAUSTED, strings con quota/exceeded
  3. is_daily_quota:
     - PerDay, quota_exceeded_daily, quotaId estructurado en error_details
     - No confunde rate limit temporal con cuota diaria
  4. is_transient_failure (app.py):
     - Daily quota (PerDay) se clasifica como PERMANENTE (no auto-retry inútil)
     - 429 RESOURCE_EXHAUSTED temporal se clasifica como TRANSIENT (auto-retry permitido)
  5. main._run_gemini_stage:
     - Manejo de backoff con delay extraído de la excepción
"""

import types
import pytest

import gemini_worker
from app import is_transient_failure


# ---------------------------------------------------------------------------
# 1. parse_retry_delay_from_exception — HTTP Headers
# ---------------------------------------------------------------------------

def test_parse_retry_delay_from_http_header_dict():
    """Exception with response.headers dict containing Retry-After."""
    class FakeResponse:
        headers = {"Retry-After": "18.5"}

    class FakeAPIError(Exception):
        response = FakeResponse()

    exc = FakeAPIError("429 Too Many Requests")
    assert gemini_worker.parse_retry_delay_from_exception(exc) == 18.5


def test_parse_retry_delay_from_http_header_case_insensitive():
    """Case-insensitive retry-after header."""
    class FakeResponse:
        headers = {"retry-after": "42s"}

    class FakeAPIError(Exception):
        response = FakeResponse()

    exc = FakeAPIError("rate limit")
    assert gemini_worker.parse_retry_delay_from_exception(exc) == 42.0


def test_parse_retry_delay_from_headers_on_exception_directly():
    """Some exceptions carry headers directly (e.g. FastAPI / requests)."""
    class FakeHTTPError(Exception):
        headers = {"Retry-After": "10"}

    exc = FakeHTTPError("429 rate limit")
    assert gemini_worker.parse_retry_delay_from_exception(exc) == 10.0


# ---------------------------------------------------------------------------
# 2. parse_retry_delay_from_exception — Structured RPC Details (RetryInfo)
# ---------------------------------------------------------------------------

def test_parse_retry_delay_from_error_details_dict_string():
    """google.rpc.RetryInfo as a JSON/dict detail with 'retryDelay' string."""
    class FakeRPCError(Exception):
        error_details = [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "22.5s"}
        ]

    exc = FakeRPCError("Resource exhausted")
    assert gemini_worker.parse_retry_delay_from_exception(exc) == 22.5


def test_parse_retry_delay_from_error_details_dict_seconds_nanos():
    """google.rpc.RetryInfo as dict with seconds and nanos."""
    class FakeRPCError(Exception):
        error_details = [
            {"retry_delay": {"seconds": 15, "nanos": 500_000_000}}
        ]

    exc = FakeRPCError("Resource exhausted")
    assert gemini_worker.parse_retry_delay_from_exception(exc) == 15.5


def test_parse_retry_delay_from_protobuf_retry_info_object():
    """google.rpc.RetryInfo as a Protobuf-like object."""
    class FakeDelay:
        seconds = 30
        nanos = 250_000_000

    class FakeRetryInfo:
        retry_delay = FakeDelay()

    class FakeRPCError(Exception):
        error_details = [FakeRetryInfo()]

    exc = FakeRPCError("Resource exhausted")
    assert gemini_worker.parse_retry_delay_from_exception(exc) == 30.25


# ---------------------------------------------------------------------------
# 3. parse_retry_delay_from_exception — gRPC Metadata & Fallback
# ---------------------------------------------------------------------------

def test_parse_retry_delay_from_grpc_trailing_metadata():
    """gRPC trailing_metadata tuple list."""
    class FakeGRPCError(Exception):
        trailing_metadata = [
            ("content-type", "application/grpc"),
            ("retry-after", "14"),
        ]

    exc = FakeGRPCError("Resource exhausted")
    assert gemini_worker.parse_retry_delay_from_exception(exc) == 14.0


def test_parse_retry_delay_from_string_fallback():
    """Falls back to regex parsing on error message when structured info is absent."""
    exc = RuntimeError("Resource exhausted: please retry in 19.3 s")
    assert gemini_worker.parse_retry_delay_from_exception(exc) == 19.3


def test_parse_retry_delay_from_none():
    assert gemini_worker.parse_retry_delay_from_exception(None) is None


# ---------------------------------------------------------------------------
# 4. is_rate_limit & is_daily_quota Classification
# ---------------------------------------------------------------------------

def test_is_rate_limit_detection():
    # By status_code
    class Err429(Exception):
        status_code = 429
    assert gemini_worker.is_rate_limit(Err429("error")) is True

    # By code attribute
    class ErrCode(Exception):
        code = 429
    assert gemini_worker.is_rate_limit(ErrCode("error")) is True

    # By string markers
    assert gemini_worker.is_rate_limit("429 RESOURCE_EXHAUSTED") is True
    assert gemini_worker.is_rate_limit("quota exceeded for model") is True
    assert gemini_worker.is_rate_limit("500 internal error") is False
    assert gemini_worker.is_rate_limit(None) is False


def test_is_daily_quota_detection():
    assert gemini_worker.is_daily_quota("Quota exceeded for quotaId: PerDayRequestsPerModel") is True
    assert gemini_worker.is_daily_quota("quota_exceeded_daily reached") is True
    assert gemini_worker.is_daily_quota("429 rate limit exceeded. retry in 10s") is False

    # Structured error_details with quotaId
    class FakeDailyQuotaError(Exception):
        error_details = [{"quotaId": "GenerateContentRequestsPerDay"}]
    assert gemini_worker.is_daily_quota(FakeDailyQuotaError("Quota")) is True


# ---------------------------------------------------------------------------
# 5. is_transient_failure (app.py) Auto-Retry Distinction
# ---------------------------------------------------------------------------

def test_transient_vs_permanent_classification_in_app():
    """Daily quota (PerDay) is PERMANENT (never auto-retry).
    Regular rate limit (RESOURCE_EXHAUSTED) is TRANSIENT (auto-retry allowed)."""

    # Transient 429 log
    transient_log = [
        "Starting job...",
        "RESOURCE_EXHAUSTED: Gemini rate limit exceeded after 6 retries. Please retry in 25s",
    ]
    assert is_transient_failure(transient_log) is True

    # Permanent daily quota log
    daily_quota_log = [
        "Starting job...",
        "RESOURCE_EXHAUSTED: Gemini daily quota exceeded (PerDay). Quota exceeded for quotaId: PerDayRequests",
    ]
    assert is_transient_failure(daily_quota_log) is False

    # Another daily quota variant
    daily_quota_log2 = [
        "RuntimeError: Daily quota exhausted for user key",
    ]
    assert is_transient_failure(daily_quota_log2) is False


# ---------------------------------------------------------------------------
# 6. Retry behavior in main._run_gemini_stage with parsed delay
# ---------------------------------------------------------------------------

def test_gemini_stage_retries_with_parsed_delay(monkeypatch):
    """When a rate limit exception carries a retry delay, _run_gemini_stage parses
    it and succeeds on next attempt without raising."""
    main = pytest.importorskip("main")

    sleeps = []
    monkeypatch.setattr(main.time, "sleep", lambda s: sleeps.append(s))

    class FakeRateLimitException(Exception):
        response = types.SimpleNamespace(headers={"Retry-After": "3.5"})

    class FakeModels:
        def __init__(self):
            self.calls = 0

        def generate_content(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise FakeRateLimitException("429 RESOURCE_EXHAUSTED")
            return types.SimpleNamespace(
                parsed={"windows": [{"id": "w1", "score": 95}]},
                candidates=[],
                usage_metadata=None,
            )

    client = types.SimpleNamespace(models=FakeModels())
    parsed, _cost = main._run_gemini_stage(client, "model", "prompt", object)
    assert parsed["windows"][0]["score"] == 95
    assert client.models.calls == 2
    assert len(sleeps) == 1
    # Slept at least the 3.5s base delay (with jitter >= 3.5 * 0.8 = 2.8)
    assert sleeps[0] >= 2.5
