"""Jetson Pipeline Viewer의 Streamlit 결과 화면."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

import streamlit as st

from .service import ViewerRun
from .tracing import FrameTrace


def render_run(run: ViewerRun) -> None:
    """분석 실행 요약과 프레임 단위 typed output을 렌더링한다."""

    st.divider()
    st.header("분석 결과")

    if run.succeeded:
        st.success(f"실제 Jetson workflow가 {len(run.frames)}프레임을 처리했습니다.")
    else:
        st.error(
            "파이프라인 실행이 중단되었습니다. 마지막 정상 commit까지 표시합니다.\n\n"
            f"{run.error_type}: {run.error_message}"
        )

    _render_summary(run)
    _render_validation_scope(run)
    if not run.frames:
        st.info("정상 commit된 프레임이 없어 프레임 Viewer를 표시할 수 없습니다.")
        return

    changed_indices = [
        index for index, frame in enumerate(run.frames) if frame.changes
    ]
    selector_columns = st.columns((2, 1))
    selected_index = selector_columns[0].slider(
        "프레임",
        min_value=0,
        max_value=len(run.frames) - 1,
        value=0,
        format="%d",
        help="정상 commit된 프레임의 0-based viewer index입니다.",
    )
    if changed_indices:
        event_index = selector_columns[1].selectbox(
            "상태 변경 프레임 바로가기",
            options=changed_indices,
            format_func=lambda index: _event_option(run.frames[index]),
        )
        if selector_columns[1].button("선택한 변경 프레임 열기", use_container_width=True):
            selected_index = int(event_index)

    selected = run.frames[selected_index]
    _render_selected_frame(selected, run)
    _render_timeline(run)


def _render_summary(run: ViewerRun) -> None:
    changed_frames = sum(bool(frame.changes) for frame in run.frames)
    degraded_frames = sum(
        frame.tracking_batch.observation.state.value != "OBSERVED"
        for frame in run.frames
    )
    elapsed_values = [
        frame.elapsed_ms for frame in run.frames if frame.elapsed_ms is not None
    ]
    average_ms = (
        sum(elapsed_values) / len(elapsed_values) if elapsed_values else 0.0
    )
    columns = st.columns(6)
    columns[0].metric("Committed frames", len(run.frames))
    columns[1].metric("Video FPS", f"{run.video_fps:.2f}")
    columns[2].metric("State-change frames", changed_frames)
    columns[3].metric("Non-observed frames", degraded_frames)
    columns[4].metric("Physical vehicles", len(run.aliases))
    columns[5].metric("Avg frame", f"{average_ms:.1f} ms")


def _render_validation_scope(run: ViewerRun) -> None:
    with st.expander("이번 실행의 검증 경계", expanded=False):
        st.markdown(
            "- **실제 사용:** EntryEventPayload, EntryEventIntake, "
            "VideoFileFrameSource, RemapFrameSource, UltralyticsVehicleTracker, "
            "MonitoringPipeline, FrameObservationWorkflow, SQLite repositories\n"
            "- **검증 제외:** 실제 카메라, Backend HTTP 전달·적용, GPIO actuator\n"
            "- **검증용 대체:** 임시 SQLite, JsonlPublicationPreparer"
        )
        st.code(str(run.model_path), language="text")


def _render_selected_frame(frame: FrameTrace, run: ViewerRun) -> None:
    st.subheader(
        f"Frame {frame.frame_id} · {_format_seconds(frame.video_seconds)}"
    )
    image_column, state_column = st.columns((3, 2))
    with image_column:
        st.image(
            frame.image_path.read_bytes(),
            caption="보정 완료 frame + 실제 tracking/domain output overlay",
            use_container_width=True,
        )
    with state_column:
        _render_frame_status(frame, run)

    tabs = st.tabs(
        (
            "이번 프레임 변경",
            "Tracking",
            "Zone visits",
            "Parking",
            "Blocking / Incident",
            "Typed output",
        )
    )
    with tabs[0]:
        _render_changes(frame)
    with tabs[1]:
        st.dataframe(_tracking_rows(frame, run), use_container_width=True)
    with tabs[2]:
        st.dataframe(_zone_visit_rows(frame, run), use_container_width=True)
    with tabs[3]:
        st.dataframe(_parking_rows(frame, run), use_container_width=True)
    with tabs[4]:
        st.caption("Blocking relations")
        st.dataframe(_blocking_rows(frame, run), use_container_width=True)
        st.caption("Incidents")
        st.dataframe(_incident_rows(frame, run), use_container_width=True)
    with tabs[5]:
        st.caption("TrackingBatch")
        st.json(_to_jsonable(frame.tracking_batch))
        st.caption("FrameObservationResult")
        st.json(_to_jsonable(frame.result))


def _render_frame_status(frame: FrameTrace, run: ViewerRun) -> None:
    observation = frame.tracking_batch.observation
    st.metric("Observation", observation.state.value)
    if observation.reason is not None:
        st.caption(f"Reason: {observation.reason.value}")

    attempt = frame.entry_attempt
    if attempt is None:
        st.warning("EntryMatchAttempt를 읽지 못했습니다.")
    else:
        st.metric("Entry match", attempt.match_state.value)
        st.caption(
            f"Decision: {attempt.decision_state.value} · "
            f"deadline {_format_seconds((attempt.match_deadline_at - frame.captured_at).total_seconds())} relative"
        )
        if attempt.matched_physical_vehicle_id is not None:
            st.code(
                f"Matched physical vehicle: {_alias(run, attempt.matched_physical_vehicle_id)}",
                language="text",
            )
        if attempt.terminal_reason:
            st.warning(attempt.terminal_reason)

    st.write(
        {
            "trackedVehicles": len(frame.tracking_batch.vehicles),
            "allDetectionsTracked": frame.tracking_batch.all_detections_tracked,
            "fullAreaObserved": frame.tracking_batch.full_area_observed,
            "activeIncidents": len(frame.result.active_incidents),
            "elapsedMs": frame.elapsed_ms,
        }
    )


def _render_changes(frame: FrameTrace) -> None:
    if not frame.changes:
        st.info("이 프레임에서 authoritative state 변경은 없습니다.")
    else:
        st.dataframe(
            [
                {
                    "category": change.category,
                    "scopeId": change.scope_id,
                    "previous": change.previous_state,
                    "current": change.current_state,
                }
                for change in frame.changes
            ],
            use_container_width=True,
        )

    parking_result = frame.result.parking_result
    st.caption("공개 transition")
    transitions = [
        {
            "type": transition.transition_type.value,
            "aggregate": "ParkingEpisode",
            "id": str(transition.parking_episode_id),
        }
        for transition in parking_result.parking_transitions
    ]
    transitions.extend(
        {
            "type": transition.transition_type.value,
            "aggregate": "Incident",
            "id": str(transition.incident.incident_id),
        }
        for transition in parking_result.incident_transitions
    )
    if transitions:
        st.dataframe(transitions, use_container_width=True)
    else:
        st.caption("이 프레임에서 materialize된 공개 transition이 없습니다.")


def _render_timeline(run: ViewerRun) -> None:
    st.subheader("상태 변경 Timeline")
    rows = []
    for frame in run.frames:
        for change in frame.changes:
            rows.append(
                {
                    "frame": frame.frame_id,
                    "videoTime": _format_seconds(frame.video_seconds),
                    "category": change.category,
                    "scopeId": change.scope_id,
                    "previous": change.previous_state,
                    "current": change.current_state,
                }
            )
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("기록된 상태 변경이 없습니다.")


def _tracking_rows(frame: FrameTrace, run: ViewerRun) -> list[dict[str, Any]]:
    progress = {
        item.physical_vehicle_id: item for item in frame.tracking_batch.absence_progress
    }
    return [
        {
            "vehicle": _alias(run, vehicle.physical_vehicle_id),
            "trackSegment": int(vehicle.track_segment_id),
            "confidence": round(vehicle.confidence, 4),
            "motion": vehicle.motion_signal.value,
            "bbox": (
                round(vehicle.bbox.x1, 4),
                round(vehicle.bbox.y1, 4),
                round(vehicle.bbox.x2, 4),
                round(vehicle.bbox.y2, 4),
            ),
            "absenceTrustedSeconds": (
                None
                if vehicle.physical_vehicle_id not in progress
                else progress[vehicle.physical_vehicle_id].trusted_seconds
            ),
        }
        for vehicle in frame.tracking_batch.vehicles
    ]


def _zone_visit_rows(frame: FrameTrace, run: ViewerRun) -> list[dict[str, Any]]:
    return [
        {
            "vehicle": _alias(run, visit.physical_vehicle_id),
            "zoneId": int(visit.zone_id),
            "state": visit.state.value,
            "entryTimer": f"{visit.entry_trusted_seconds:.3f}/{visit.entry_confirmation_seconds:.3f}",
            "exitTimer": f"{visit.exit_trusted_seconds:.3f}/{visit.exit_confirmation_seconds:.3f}",
            "observation": visit.observation.state.value,
            "version": visit.record_version,
        }
        for visit in frame.zone_visits
    ]


def _parking_rows(frame: FrameTrace, run: ViewerRun) -> list[dict[str, Any]]:
    return [
        {
            "vehicle": _alias(run, episode.physical_vehicle_id),
            "state": episode.state.value,
            "signal": episode.last_signal.value,
            "stationaryTimer": f"{episode.stationary_trusted_seconds:.3f}/{episode.parking_confirmation_seconds:.3f}",
            "movementTimer": f"{episode.movement_trusted_seconds:.3f}/{episode.movement_confirmation_seconds:.3f}",
            "assignment": (
                None if episode.assignment is None else episode.assignment.state.value
            ),
            "zoneId": (
                None if episode.assignment is None else episode.assignment.zone_id
            ),
            "version": episode.record_version,
        }
        for episode in frame.parking_episodes
    ]


def _blocking_rows(frame: FrameTrace, run: ViewerRun) -> list[dict[str, Any]]:
    return [
        {
            "subject": _alias(run, relation.subject_physical_vehicle_id),
            "victim": _alias(run, relation.victim_physical_vehicle_id),
            "egressZoneId": int(relation.egress_zone_id),
            "state": relation.state.value,
            "confirmTimer": f"{relation.confirm_trusted_seconds:.3f}/{relation.confirm_duration_seconds:.3f}",
            "clearTimer": f"{relation.clear_trusted_seconds:.3f}/{relation.clear_duration_seconds:.3f}",
        }
        for relation in frame.blocking_relations
    ]


def _incident_rows(frame: FrameTrace, run: ViewerRun) -> list[dict[str, Any]]:
    return [
        {
            "vehicle": _alias(run, incident.physical_vehicle_id),
            "rule": incident.key.rule_code,
            "state": incident.state.value,
            "zoneId": incident.zone_id,
            "sessionId": incident.parking_session_id,
            "publicationRevision": incident.publication_revision,
            "observation": incident.observation.state.value,
        }
        for incident in frame.incidents
    ]


def _event_option(frame: FrameTrace) -> str:
    labels = ", ".join(change.label for change in frame.changes[:2])
    if len(frame.changes) > 2:
        labels += f" 외 {len(frame.changes) - 2}건"
    return f"F{frame.frame_id} {_format_seconds(frame.video_seconds)} · {labels}"


def _alias(run: ViewerRun, physical_vehicle_id: Any) -> str:
    return run.aliases.get(physical_vehicle_id, str(physical_vehicle_id)[:8])


def _format_seconds(value: float) -> str:
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    minutes, seconds = divmod(absolute, 60.0)
    return f"{sign}{int(minutes):02d}:{seconds:06.3f}"


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, UUID, Path)):
        return str(value)
    if is_dataclass(value):
        return {
            item.name: _to_jsonable(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_to_jsonable(item) for item in value]
    return repr(value)
