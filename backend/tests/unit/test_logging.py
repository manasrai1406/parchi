import json

import pytest

from parchi.config import AppEnv, Settings
from parchi.logging import bind_context, clear_context, configure_logging, get_logger


@pytest.fixture
def json_log_lines(capsys: pytest.CaptureFixture[str]):
    """Call it once to switch on JSON logging, then again to read the lines written.

    Logging is configured inside the test body because the handler binds to the
    stderr that pytest's capture has active at that moment.
    """
    configured = False

    def lines() -> list[dict]:
        nonlocal configured
        if not configured:
            configure_logging(Settings(_env_file=None, app_env=AppEnv.PRODUCTION, log_dir=None))
            clear_context()
            configured = True
            return []
        err = capsys.readouterr().err
        return [json.loads(line) for line in err.splitlines() if line.startswith("{")]

    yield lines
    clear_context()


def test_bound_ids_appear_on_every_line(json_log_lines) -> None:
    json_log_lines()
    bind_context(request_id="req-12345678", file_id=7, ref_no="REF-2026-000007")
    log = get_logger("parchi.tests")
    log.info("stage.started")
    log.info("stage.finished", duration_ms=12)

    lines = json_log_lines()
    assert [line["event"] for line in lines] == ["stage.started", "stage.finished"]
    for line in lines:
        assert line["request_id"] == "req-12345678"
        assert line["file_id"] == 7
        assert line["ref_no"] == "REF-2026-000007"


def test_sensitive_values_are_redacted(json_log_lines) -> None:
    json_log_lines()
    get_logger("parchi.tests").info(
        "oops",
        api_key="sk-live-123",
        anthropic_api_key="sk-ant-456",
        text="TOTAL 1,234.00",
        ocr_text="HP PETROL PUMP",
        field="total",
    )

    (line,) = json_log_lines()
    raw = json.dumps(line)
    for secret in ("sk-live-123", "sk-ant-456", "1,234.00", "HP PETROL PUMP"):
        assert secret not in raw
    assert line["field"] == "total"


def test_unknown_context_keys_are_refused() -> None:
    with pytest.raises(ValueError, match="vendor"):
        bind_context(vendor="Bharat Petroleum")
