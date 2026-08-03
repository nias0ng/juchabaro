"""영상 00:00부터 실제 Jetson 판정 변화를 보여주는 Streamlit 앱."""

from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st


st.set_page_config(page_title="Jetson Pipeline Viewer", layout="wide")

VIEWER_DIR = Path(__file__).resolve().parent
TRACKING_DIR = VIEWER_DIR.parent
JETSON_ROOT = VIEWER_DIR.parents[2] / "hw" / "jetson"
for import_root in (TRACKING_DIR, JETSON_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))


from pipeline_viewer.service import (  # noqa: E402
    VideoUpload,
    ViewerInputError,
    ViewerPaths,
    ViewerPolicy,
    ViewerRun,
    ViewerRunRequest,
    build_allow_example,
    cleanup_run,
    default_idempotency_key,
    default_paths,
    run_viewer_pipeline,
)
from pipeline_viewer.ui import render_run  # noqa: E402


ENTRY_JSON_KEY = "jetson_viewer_entry_json"
IDEMPOTENCY_KEY = "jetson_viewer_idempotency_key"
RUN_KEY = "jetson_viewer_run"


def _initialize_example() -> None:
    if ENTRY_JSON_KEY not in st.session_state:
        example = build_allow_example()
        st.session_state[ENTRY_JSON_KEY] = example
        st.session_state[IDEMPOTENCY_KEY] = default_idempotency_key(example)


def _replace_example() -> None:
    previous = st.session_state.get(RUN_KEY)
    if isinstance(previous, ViewerRun):
        cleanup_run(previous)
        st.session_state.pop(RUN_KEY, None)
    example = build_allow_example()
    st.session_state[ENTRY_JSON_KEY] = example
    st.session_state[IDEMPOTENCY_KEY] = default_idempotency_key(example)


def _render_policy_inputs() -> ViewerPolicy:
    defaults = ViewerPolicy()
    with st.expander("Monitoring / tracker 설정", expanded=False):
        st.caption(
            "모든 값은 실제 MonitoringPolicy와 adapter에 그대로 전달됩니다. "
            "1.0초 blocking 값 등 실측 전 값은 provisional입니다."
        )
        columns = st.columns(4)
        zone_entry = columns[0].number_input(
            "Zone entry confirm (s)", min_value=0.0, value=defaults.zone_entry_confirm_seconds
        )
        zone_exit = columns[1].number_input(
            "Zone exit confirm (s)", min_value=0.0, value=defaults.zone_exit_confirm_seconds
        )
        parking_confirm = columns[2].number_input(
            "Parking confirm (s)", min_value=0.001, value=defaults.parking_confirm_seconds
        )
        parking_move = columns[3].number_input(
            "Parking move confirm (s)", min_value=0.0, value=defaults.parking_move_confirm_seconds
        )

        columns = st.columns(4)
        absence = columns[0].number_input(
            "Absence confirm (s)", min_value=0.001, value=defaults.absence_confirmation_seconds
        )
        trusted_gap = columns[1].number_input(
            "Trusted max gap (s)", min_value=0.001, value=defaults.trusted_sample_max_gap_seconds
        )
        incident_confirm = columns[2].number_input(
            "Incident confirm (s)", min_value=0.0, value=defaults.incident_confirm_seconds
        )
        incident_clear = columns[3].number_input(
            "Incident clear (s)", min_value=0.0, value=defaults.incident_clear_seconds
        )

        columns = st.columns(4)
        entry_overlap = columns[0].number_input(
            "Entry overlap", min_value=0.0, max_value=1.0, value=defaults.entry_zone_min_overlap_ratio
        )
        zone_overlap = columns[1].number_input(
            "Zone presence overlap", min_value=0.0, max_value=1.0, value=defaults.zone_presence_min_overlap_ratio
        )
        assignment_overlap = columns[2].number_input(
            "Assignment overlap", min_value=0.0, max_value=1.0, value=defaults.assignment_min_overlap_ratio
        )
        ambiguous_margin = columns[3].number_input(
            "Assignment margin", min_value=0.0, max_value=1.0, value=defaults.assignment_ambiguous_margin
        )

        columns = st.columns(4)
        blocking_confirm = columns[0].number_input(
            "Blocking confirm (s)", min_value=0.0, value=defaults.blocking_relation_confirm_seconds
        )
        blocking_clear = columns[1].number_input(
            "Blocking clear (s)", min_value=0.0, value=defaults.blocking_relation_clear_seconds
        )
        match_window = columns[2].number_input(
            "Entry match window (s)", min_value=0.001, value=defaults.entry_match_window_seconds
        )
        movement_epsilon = columns[3].number_input(
            "Movement epsilon", min_value=0.0, value=defaults.movement_epsilon, format="%.4f"
        )

        columns = st.columns(4)
        confidence = columns[0].number_input(
            "YOLO confidence", min_value=0.0, max_value=1.0, value=defaults.confidence
        )
        remap_balance = columns[1].number_input(
            "Remap balance", min_value=0.0, max_value=1.0, value=defaults.remap_balance
        )
        tracker_config = columns[2].text_input(
            "Tracker config", value=defaults.tracker_config
        )

    return ViewerPolicy(
        zone_entry_confirm_seconds=zone_entry,
        zone_exit_confirm_seconds=zone_exit,
        entry_zone_min_overlap_ratio=entry_overlap,
        parking_confirm_seconds=parking_confirm,
        parking_move_confirm_seconds=parking_move,
        absence_confirmation_seconds=absence,
        trusted_sample_max_gap_seconds=trusted_gap,
        incident_confirm_seconds=incident_confirm,
        incident_clear_seconds=incident_clear,
        zone_presence_min_overlap_ratio=zone_overlap,
        assignment_min_overlap_ratio=assignment_overlap,
        assignment_ambiguous_margin=ambiguous_margin,
        blocking_relation_confirm_seconds=blocking_confirm,
        blocking_relation_clear_seconds=blocking_clear,
        entry_match_window_seconds=match_window,
        movement_epsilon=movement_epsilon,
        confidence=confidence,
        tracker_config=tracker_config,
        remap_balance=remap_balance,
    )


def main() -> None:
    _initialize_example()
    paths = default_paths()

    st.title("Jetson Tracking Pipeline Viewer")
    st.caption(
        "영상 00:00을 입차 순간으로 두고 실제 EntryEventIntake와 "
        "MonitoringPipeline의 commit 결과를 프레임별로 관찰합니다."
    )

    if st.button("새 synthetic ALLOW 예시", help="UUID와 idempotency key를 새로 만듭니다."):
        _replace_example()
        st.rerun()

    input_columns = st.columns(2)
    with input_columns[0]:
        st.subheader("입차 이벤트")
        entry_json = st.text_area(
            "현재 Jetson API wire JSON",
            key=ENTRY_JSON_KEY,
            height=330,
            help="예시는 임시 DB에만 들어가며 실제 EntryEventPayload로 검증됩니다.",
        )
        idempotency_key = st.text_input(
            "Idempotency-Key",
            key=IDEMPOTENCY_KEY,
        )
    with input_columns[1]:
        st.subheader("입차 순간부터 시작하는 영상")
        video = st.file_uploader(
            "동영상 입력",
            type=("mp4", "avi", "mov", "mkv"),
            accept_multiple_files=False,
            help="첫 프레임을 입차 이벤트의 entryTime과 같은 00:00.000으로 처리합니다.",
        )
        if video is None:
            st.info("분석할 영상을 업로드하세요.")
        else:
            st.video(video.getvalue())
            st.caption(f"{video.name} · {video.size:,} bytes")

    st.subheader("Runtime 경로")
    path_columns = st.columns(3)
    model_path = Path(
        path_columns[0].text_input("YOLO model", value=str(paths.model))
    )
    zones_path = Path(
        path_columns[1].text_input("Zone definition", value=str(paths.zones))
    )
    calibration_path = Path(
        path_columns[2].text_input("Calibration", value=str(paths.calibration))
    )
    st.caption("기본 모델 위치: hw/jetson/model/yolo26n.pt")

    end_seconds_value = st.number_input(
        "분석 종료 시각(초, 0이면 영상 끝까지)",
        min_value=0.0,
        value=0.0,
    )
    policy = _render_policy_inputs()

    run_requested = st.button(
        "실제 Jetson workflow 분석 실행",
        type="primary",
        use_container_width=True,
        disabled=video is None,
    )
    if run_requested and video is not None:
        previous = st.session_state.get(RUN_KEY)
        if isinstance(previous, ViewerRun):
            cleanup_run(previous)
            st.session_state.pop(RUN_KEY, None)

        progress = st.progress(0.0, text="입력 검증과 runtime 조립 중...")

        def report_progress(current: int, total: int | None) -> None:
            if total is None or total <= 0:
                progress.progress(0.0, text=f"{current}프레임 처리")
                return
            progress.progress(
                min(1.0, current / total),
                text=f"{current}/{total}프레임 처리",
            )

        request = ViewerRunRequest(
            entry_event_json=entry_json,
            idempotency_key=idempotency_key,
            video=VideoUpload(file_name=video.name, content=video.getvalue()),
            paths=ViewerPaths(
                model=model_path,
                zones=zones_path,
                calibration=calibration_path,
            ),
            policy=policy,
            end_seconds=None if end_seconds_value == 0.0 else end_seconds_value,
        )
        try:
            run = run_viewer_pipeline(request, progress_callback=report_progress)
        except ViewerInputError as exc:
            progress.empty()
            st.error(str(exc))
        except Exception as exc:
            progress.empty()
            st.error(f"Viewer 조립에 실패했습니다: {type(exc).__name__}: {exc}")
        else:
            progress.progress(1.0, text="분석 완료")
            st.session_state[RUN_KEY] = run

    previous_run = st.session_state.get(RUN_KEY)
    if isinstance(previous_run, ViewerRun):
        render_run(previous_run)


if __name__ == "__main__":
    main()
