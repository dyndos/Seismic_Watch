from __future__ import annotations

from datetime import datetime, timezone

from research.run_blind_test import DAY_MS, select_cutoffs


def ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def feature(event_id: str, origin: str, magnitude: float = 7.0) -> dict:
    return {
        "id": event_id,
        "properties": {"time": ms(origin), "mag": magnitude},
        "geometry": {"coordinates": [120.0, 10.0, 15.0]},
    }


def test_exact_date_window_is_start_inclusive_end_exclusive() -> None:
    events = [
        feature("before", "2022-12-31T23:59:59Z"),
        feature("jan", "2023-01-01T00:00:00Z"),
        feature("june", "2023-06-30T23:59:59Z"),
        feature("july", "2023-07-01T00:00:00Z"),
    ]
    gcmt = {
        event["id"]: {
            "solution_update_ms": event["properties"]["time"] + 2 * DAY_MS,
            "event_name": event["id"],
        }
        for event in events
        if event["id"] not in ("before", "july")
    }
    selected = select_cutoffs(
        events,
        2023,
        2023,
        0,
        False,
        gcmt,
        ms("2026-01-01T00:00:00Z"),
        start_date="2023-01-01T00:00:00Z",
        end_date="2023-07-01T00:00:00Z",
    )
    assert [row["trigger_event_id"] for row in selected] == ["jan", "june"]


def test_max_triggers_is_applied_after_date_filter_and_is_evenly_spaced() -> None:
    events = [
        feature(f"event-{i:02d}", f"2023-{1 + (i // 4):02d}-{1 + (i % 4):02d}T00:00:00Z")
        for i in range(20)
    ]
    gcmt = {
        event["id"]: {
            "solution_update_ms": event["properties"]["time"] + 2 * DAY_MS,
            "event_name": event["id"],
        }
        for event in events
    }
    selected = select_cutoffs(
        events,
        2023,
        2023,
        10,
        False,
        gcmt,
        ms("2026-01-01T00:00:00Z"),
        start_date="2023-01-01T00:00:00Z",
        end_date="2023-07-01T00:00:00Z",
    )
    assert len(selected) == 10
    assert selected[0]["trigger_event_id"] == "event-00"
    assert selected[-1]["trigger_event_id"] == "event-19"
