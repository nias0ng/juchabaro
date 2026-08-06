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
from src.config.monitoring_policy import INCIDENT_RULE_TIMING_SPECS  # noqa: E402


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
    """Owner 경계와 판정 흐름 순서로 Viewer 설정을 입력받는다."""

    defaults = ViewerPolicy()
    values: dict[str, object] = {}
    with st.expander("Monitoring / tracker 설정", expanded=False):
        st.caption(
            "설정은 판정 흐름과 Owner 경계 순서로 나눴습니다. Viewer의 YOLO confidence "
            "0.01은 낮은 confidence 분포를 export하기 위한 진단용 기본값입니다."
        )
        detection_tab, observation_tab, zone_tab, parking_tab, incident_tab = st.tabs(
            ("탐지·동일성", "관측·Motion", "Zone·Assignment", "Parking·Blocking", "Incident")
        )

        with detection_tab:
            st.caption("Detector → TrackSegment → PhysicalVehicle 동일성")
            columns = st.columns(4)
            values["confidence"] = columns[0].number_input(
                "YOLO confidence",
                min_value=0.0,
                max_value=1.0,
                value=defaults.confidence,
                format="%.4f",
                help="진단용 provisional 값입니다. 배포 기본값과 구분해 export합니다.",
            )
            values["tracker_config"] = columns[1].text_input(
                "Tracker config", value=defaults.tracker_config
            )
            values["mask_margin_ratio"] = columns[2].number_input(
                "Side mask margin ratio",
                min_value=0.0,
                max_value=1.0,
                value=defaults.mask_margin_ratio,
                format="%.4f",
            )
            values["remap_balance"] = columns[3].number_input(
                "Remap balance",
                min_value=0.0,
                max_value=1.0,
                value=defaults.remap_balance,
            )

            columns = st.columns(3)
            values["reidentification_max_gap_seconds"] = columns[0].number_input(
                "Re-ID max gap (s)",
                min_value=0.001,
                value=defaults.reidentification_max_gap_seconds,
            )
            values["reidentification_min_score"] = columns[1].number_input(
                "Re-ID min score",
                min_value=0.0,
                max_value=1.0,
                value=defaults.reidentification_min_score,
            )
            values["reidentification_ambiguity_margin"] = columns[2].number_input(
                "Re-ID ambiguity margin",
                min_value=0.0,
                max_value=1.0,
                value=defaults.reidentification_ambiguity_margin,
            )

        with observation_tab:
            st.caption("관측 공백과 MotionEstimator 신뢰성 기준")
            columns = st.columns(4)
            values["absence_confirmation_seconds"] = columns[0].number_input(
                "Absence confirm (s)",
                min_value=0.001,
                value=defaults.absence_confirmation_seconds,
            )
            values["trusted_sample_max_gap_seconds"] = columns[1].number_input(
                "Trusted max gap (s)",
                min_value=0.001,
                value=defaults.trusted_sample_max_gap_seconds,
            )
            values["motion_window_seconds"] = columns[2].number_input(
                "Motion window (s)",
                min_value=0.001,
                value=defaults.motion_window_seconds,
            )
            values["motion_min_observation_span_seconds"] = columns[3].number_input(
                "Motion min span (s)",
                min_value=0.001,
                value=defaults.motion_min_observation_span_seconds,
            )

            columns = st.columns(4)
            values["motion_max_sample_gap_seconds"] = columns[0].number_input(
                "Motion max sample gap (s)",
                min_value=0.001,
                value=defaults.motion_max_sample_gap_seconds,
                help="Parking move confirm과 별개의 Motion history 연속성 기준입니다.",
            )
            values["motion_min_samples"] = int(
                columns[1].number_input(
                    "Motion min samples",
                    min_value=3,
                    step=1,
                    value=defaults.motion_min_samples,
                )
            )
            values["motion_stationary_threshold"] = columns[2].number_input(
                "Stationary threshold",
                min_value=0.0001,
                value=defaults.motion_stationary_threshold,
                format="%.4f",
            )
            values["motion_moving_threshold"] = columns[3].number_input(
                "Moving threshold",
                min_value=0.0001,
                value=defaults.motion_moving_threshold,
                format="%.4f",
            )
            values["motion_min_trend_consistency"] = st.number_input(
                "Motion trend consistency",
                min_value=0.0001,
                max_value=1.0,
                value=defaults.motion_min_trend_consistency,
                format="%.4f",
            )

        with zone_tab:
            st.caption("ZoneVisit → footprint overlap → Assignment/BAD_PARKING")
            columns = st.columns(4)
            values["zone_entry_confirm_seconds"] = columns[0].number_input(
                "Zone entry confirm (s)",
                min_value=0.0,
                value=defaults.zone_entry_confirm_seconds,
            )
            values["zone_exit_confirm_seconds"] = columns[1].number_input(
                "Zone exit confirm (s)",
                min_value=0.0,
                value=defaults.zone_exit_confirm_seconds,
            )
            values["entry_match_window_seconds"] = columns[2].number_input(
                "Entry match window (s)",
                min_value=0.001,
                value=defaults.entry_match_window_seconds,
            )
            values["entry_zone_min_overlap_ratio"] = columns[3].number_input(
                "Entry overlap",
                min_value=0.0,
                max_value=1.0,
                value=defaults.entry_zone_min_overlap_ratio,
            )

            columns = st.columns(4)
            values["zone_presence_min_overlap_ratio"] = columns[0].number_input(
                "Zone presence overlap",
                min_value=0.0,
                max_value=1.0,
                value=defaults.zone_presence_min_overlap_ratio,
            )
            values["assignment_min_overlap_ratio"] = columns[1].number_input(
                "Assignment overlap",
                min_value=0.0,
                max_value=1.0,
                value=defaults.assignment_min_overlap_ratio,
            )
            values["assignment_ambiguous_margin"] = columns[2].number_input(
                "Assignment margin",
                min_value=0.0,
                max_value=1.0,
                value=defaults.assignment_ambiguous_margin,
            )
            values["out_of_zone_min_spot_overlap_ratio"] = columns[3].number_input(
                "Out-of-zone spot-union overlap",
                min_value=0.0,
                max_value=1.0,
                value=defaults.out_of_zone_min_spot_overlap_ratio,
            )

            columns = st.columns(2)
            values["bad_parking_min_primary_overlap_ratio"] = columns[0].number_input(
                "BAD_PARKING primary overlap",
                min_value=0.0,
                max_value=1.0,
                value=defaults.bad_parking_min_primary_overlap_ratio,
                help="주 할당 면적이 이 값 미만이면 BAD_PARKING 근거가 됩니다.",
            )
            values["bad_parking_min_secondary_overlap_ratio"] = columns[1].number_input(
                "BAD_PARKING secondary overlap",
                min_value=0.0,
                max_value=1.0,
                value=defaults.bad_parking_min_secondary_overlap_ratio,
                help="두 번째 주차면 overlap이 이 값 이상이면 두 칸 차지 근거가 됩니다.",
            )

        with parking_tab:
            st.caption("ParkingEpisode lifecycle과 BlockingRelation 안정화 시간")
            columns = st.columns(4)
            values["parking_confirm_seconds"] = columns[0].number_input(
                "Parking confirm (s)",
                min_value=0.001,
                value=defaults.parking_confirm_seconds,
            )
            values["parking_move_confirm_seconds"] = columns[1].number_input(
                "Parking move confirm (s)",
                min_value=0.0,
                value=defaults.parking_move_confirm_seconds,
            )
            values["blocking_relation_confirm_seconds"] = columns[2].number_input(
                "Blocking confirm (s)",
                min_value=0.0,
                value=defaults.blocking_relation_confirm_seconds,
            )
            values["blocking_relation_clear_seconds"] = columns[3].number_input(
                "Blocking clear (s)",
                min_value=0.0,
                value=defaults.blocking_relation_clear_seconds,
            )

            columns = st.columns(2)
            values["blocking_min_subject_overlap_ratio"] = columns[0].number_input(
                "Blocking subject overlap",
                min_value=0.01,
                max_value=1.0,
                value=defaults.blocking_min_subject_overlap_ratio,
                step=0.01,
            )
            values["blocking_min_egress_coverage_ratio"] = columns[1].number_input(
                "Blocking egress coverage",
                min_value=0.01,
                max_value=1.0,
                value=defaults.blocking_min_egress_coverage_ratio,
                step=0.01,
            )

        with incident_tab:
            st.caption(
                "전역 값은 목록에 없는 future rule의 fallback입니다. "
                "현재 규칙은 아래 confirm/clear 정책을 우선 사용합니다."
            )
            columns = st.columns(2)
            values["incident_confirm_seconds"] = columns[0].number_input(
                "Fallback incident confirm (s)",
                min_value=0.0,
                value=defaults.incident_confirm_seconds,
            )
            values["incident_clear_seconds"] = columns[1].number_input(
                "Fallback incident clear (s)",
                min_value=0.0,
                value=defaults.incident_clear_seconds,
            )

            group_labels = {
                "CONTEXT": "권한·세션 규칙",
                "GEOMETRY": "기하·배치 규칙",
                "RELATION": "차단 관계 규칙",
            }
            for group in ("CONTEXT", "GEOMETRY", "RELATION"):
                st.markdown(f"**{group_labels[group]}**")
                header = st.columns((2, 1, 1))
                header[0].caption("Rule")
                header[1].caption("Confirm (s)")
                header[2].caption("Clear (s)")
                for spec in INCIDENT_RULE_TIMING_SPECS:
                    if spec.group != group:
                        continue
                    columns = st.columns((2, 1, 1))
                    columns[0].code(spec.rule_code)
                    values[spec.confirm_field] = columns[1].number_input(
                        f"{spec.rule_code} confirm (s)",
                        min_value=0.0,
                        value=getattr(defaults, spec.confirm_field),
                        label_visibility="collapsed",
                    )
                    values[spec.clear_field] = columns[2].number_input(
                        f"{spec.rule_code} clear (s)",
                        min_value=0.0,
                        value=getattr(defaults, spec.clear_field),
                        label_visibility="collapsed",
                    )

    return ViewerPolicy(**values)

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
    path_columns = st.columns(4)
    model_path = Path(
        path_columns[0].text_input("YOLO model", value=str(paths.model))
    )
    zones_path = Path(
        path_columns[1].text_input("Zone definition", value=str(paths.zones))
    )
    egress_aisles_path = Path(
        path_columns[2].text_input(
            "Egress aisle definition", value=str(paths.egress_aisles)
        )
    )
    calibration_path = Path(
        path_columns[3].text_input("Calibration", value=str(paths.calibration))
    )
    st.caption("기본 모델 위치: hw/jetson/model/yolov8s.pt")

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
                egress_aisles=egress_aisles_path,
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
