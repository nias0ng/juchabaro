"""Pipeline Viewer 설정 UI의 Owner별 탐색 계약."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_policy_settings_are_grouped_in_owner_flow_order() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=20)

    assert list(app.exception) == []
    assert [tab.label for tab in app.tabs] == [
        "탐지·동일성",
        "관측·Motion",
        "Zone·Assignment",
        "Parking·Blocking",
        "Incident",
    ]
    labels = {control.label for control in app.number_input}
    assert {
        "YOLO confidence",
        "Re-ID max gap (s)",
        "Motion max sample gap (s)",
        "EXIT re-entry confirm (s)",
        "BAD_PARKING secondary overlap",
        "Parking move confirm (s)",
        "BAD_PARKING confirm (s)",
    }.issubset(labels)

    ordered_labels = [control.label for control in app.number_input]
    zone_policy_labels = [
        "Zone entry confirm (s)",
        "Zone exit confirm (s)",
        "EXIT re-entry confirm (s)",
        "Entry match window (s)",
        "Entry overlap",
        "Zone presence overlap",
        "Assignment overlap",
        "Assignment margin",
        "BAD_PARKING primary overlap",
        "BAD_PARKING secondary overlap",
        "Out-of-zone spot-union overlap",
    ]
    zone_start = ordered_labels.index(zone_policy_labels[0])
    assert ordered_labels[
        zone_start : zone_start + len(zone_policy_labels)
    ] == zone_policy_labels
