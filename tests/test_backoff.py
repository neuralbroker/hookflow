"""Backoff schedule is exponential and bounded."""

from app.worker import backoff_delay_seconds


def test_backoff_grows():
    schedule = [60, 300, 1800, 7200, 43200]
    assert backoff_delay_seconds(1, schedule) == 60
    assert backoff_delay_seconds(2, schedule) == 300
    assert backoff_delay_seconds(5, schedule) == 43200


def test_backoff_repeats_last_past_schedule():
    schedule = [60, 300]
    assert backoff_delay_seconds(9, schedule) == 300
