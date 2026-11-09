from datetime import datetime, timezone

from research.global_catalog import fetch_comcat


def test_comcat_fetch_advances_across_year_boundary_once(monkeypatch):
    calls = []

    def fake_window(session, start, end, min_mag, depth=8):
        calls.append((start, end, min_mag))
        return []

    monkeypatch.setattr("research.global_catalog._fetch_window", fake_window)
    payload, manifest = fetch_comcat("2022-12-31", "2023-01-01", 5.0)

    assert len(calls) == 2
    assert calls[0][0] == datetime(2022, 12, 31, 0, 0, tzinfo=timezone.utc)
    assert calls[0][1] == datetime(2022, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    assert calls[1][0] == datetime(2023, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert calls[1][1] == datetime(2023, 1, 1, 23, 59, 59, tzinfo=timezone.utc)
    assert payload["features"] == []
    assert manifest["raw_count"] == 0
