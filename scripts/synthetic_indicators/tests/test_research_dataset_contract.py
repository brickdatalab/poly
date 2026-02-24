from pathlib import Path


def test_canonical_dataset_sql_contains_core_fields():
    sql = Path("scripts/synthetic_indicators/research/sql/canonical_signal_dataset.sql").read_text()
    required = [
        "event_open",
        "event_close",
        "event_return",
        "outcome",
        "decision_phase",
        "source_time",
        "computed_at",
        "atr_14_15m",
    ]
    for token in required:
        assert token in sql


def test_builder_has_source_time_validity_guard():
    py = Path("scripts/synthetic_indicators/research/build_canonical_signal_dataset.py").read_text()
    assert "source_time_valid" in py
    assert "decision_deadline" in py
