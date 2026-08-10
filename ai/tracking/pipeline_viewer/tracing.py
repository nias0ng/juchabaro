"""정상 commit된 Jetson 프레임을 viewer용 읽기 모델로 보존한다.

입력은 ``MonitoringPipeline.frame_observer``가 전달한 실제
``CapturedFrame``·``TrackingBatch``·``FrameObservationResult``다. 상태 변화는
운영 aggregate snapshot의 ``state`` 차이만 표시하며 domain 판정을 재구현하지
않는다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

from src.application.frame_observation_workflow import FrameObservationResult
from src.camera.frame_source import EPOCH
from src.camera.models import CapturedFrame
from src.parking.models import (
    BlockingRelation,
    Incident,
    ParkingEpisode,
    ZoneDefinition,
    ZoneVisit,
)
from src.session.models import EntryAttemptId, EntryMatchAttempt
from src.storage.repositories import EntryMatchAttemptRepository
from src.tracking.models import PhysicalVehicleId, TrackingBatch

from .overlay import draw_frame_overlay, write_jpeg


ConnectionFactory = Callable[[], sqlite3.Connection]


@dataclass(frozen=True, slots=True)
class StateChange:
    """한 commit에서 authoritative snapshot의 state가 달라진 사실."""

    category: str
    scope_id: str
    previous_state: str | None
    current_state: str

    @property
    def label(self) -> str:
        previous = self.previous_state or "(created)"
        return f"{self.category} {previous} → {self.current_state}"


@dataclass(slots=True)
class FrameTrace:
    """한 정상 commit 프레임의 typed output과 viewer projection."""

    frame_id: int
    video_seconds: float
    captured_at: datetime
    image_path: Path
    tracking_batch: TrackingBatch
    result: FrameObservationResult
    entry_attempt: EntryMatchAttempt | None
    zone_visits: tuple[ZoneVisit, ...]
    parking_episodes: tuple[ParkingEpisode, ...]
    blocking_relations: tuple[BlockingRelation, ...]
    incidents: tuple[Incident, ...]
    changes: tuple[StateChange, ...]
    elapsed_ms: float | None = None


@dataclass(slots=True)
class TraceCollector:
    """실제 frame observer 출력을 JPEG와 immutable typed snapshot으로 모은다."""

    frames_directory: Path
    zones: Sequence[ZoneDefinition]
    entry_attempt_id: EntryAttemptId
    connection_factory: ConnectionFactory
    frames: list[FrameTrace] = field(default_factory=list)
    _aliases: dict[PhysicalVehicleId, str] = field(default_factory=dict)
    _zone_visits: dict[str, ZoneVisit] = field(default_factory=dict)
    _parking_episodes: dict[str, ParkingEpisode] = field(default_factory=dict)
    _blocking_relations: dict[str, BlockingRelation] = field(default_factory=dict)
    _incidents: dict[str, Incident] = field(default_factory=dict)
    _entry_attempt: EntryMatchAttempt | None = None

    def alias_for(self, physical_vehicle_id: PhysicalVehicleId) -> str:
        """실행 안에서만 안정적인 짧은 차량 별칭을 반환한다."""

        alias = self._aliases.get(physical_vehicle_id)
        if alias is None:
            alias = f"V{len(self._aliases) + 1}"
            self._aliases[physical_vehicle_id] = alias
        return alias

    @property
    def aliases(self) -> dict[PhysicalVehicleId, str]:
        return dict(self._aliases)

    def observe(
        self,
        frame: CapturedFrame,
        tracking_batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        """정상 commit 뒤 실제 output을 projection하고 overlay JPEG를 남긴다."""

        for vehicle in tracking_batch.vehicles:
            self.alias_for(vehicle.physical_vehicle_id)
        for physical_vehicle_id in tracking_batch.unobserved_physical_vehicle_ids:
            self.alias_for(physical_vehicle_id)

        changes: list[StateChange] = []
        parking_result = result.parking_result
        for visit in parking_result.zone_visit_updates:
            self.alias_for(visit.physical_vehicle_id)
        for episode in parking_result.parking_episode_updates:
            self.alias_for(episode.physical_vehicle_id)
        for relation in parking_result.blocking_relation_updates:
            self.alias_for(relation.subject_physical_vehicle_id)
            self.alias_for(relation.victim_physical_vehicle_id)
        for incident in (*parking_result.incident_updates, *result.active_incidents):
            self.alias_for(incident.physical_vehicle_id)
        self._apply_updates(
            self._zone_visits,
            parking_result.zone_visit_updates,
            id_attribute="visit_id",
            category="ZoneVisit",
            changes=changes,
        )
        self._apply_updates(
            self._parking_episodes,
            parking_result.parking_episode_updates,
            id_attribute="episode_id",
            category="ParkingEpisode",
            changes=changes,
        )
        self._apply_updates(
            self._blocking_relations,
            parking_result.blocking_relation_updates,
            id_attribute="blocking_relation_id",
            category="BlockingRelation",
            changes=changes,
        )
        self._apply_updates(
            self._incidents,
            parking_result.incident_updates,
            id_attribute="incident_id",
            category="Incident",
            changes=changes,
        )

        entry_attempt = self._load_entry_attempt()
        if entry_attempt is not None:
            previous_state = (
                None
                if self._entry_attempt is None
                else self._entry_attempt.match_state.value
            )
            current_state = entry_attempt.match_state.value
            if previous_state != current_state:
                changes.append(
                    StateChange(
                        category="EntryMatch",
                        scope_id=str(entry_attempt.entry_attempt_id),
                        previous_state=previous_state,
                        current_state=current_state,
                    )
                )
            self._entry_attempt = entry_attempt

        overlay = draw_frame_overlay(
            frame.image,
            tracking_batch=tracking_batch,
            result=result,
            zones=self.zones,
            alias_for=self.alias_for,
        )
        image_path = self.frames_directory / f"frame_{frame.frame_id:08d}.jpg"
        write_jpeg(image_path, overlay)

        self.frames.append(
            FrameTrace(
                frame_id=frame.frame_id,
                video_seconds=(frame.captured_at - EPOCH).total_seconds(),
                captured_at=frame.captured_at,
                image_path=image_path,
                tracking_batch=tracking_batch,
                result=result,
                entry_attempt=entry_attempt,
                zone_visits=_ordered_values(self._zone_visits),
                parking_episodes=_ordered_values(self._parking_episodes),
                blocking_relations=_ordered_values(self._blocking_relations),
                incidents=_ordered_values(self._incidents),
                changes=tuple(changes),
            )
        )

    def set_last_elapsed_ms(self, elapsed_ms: float) -> None:
        """observer를 포함한 마지막 ``process_next_frame`` 시간을 기록한다."""

        if not self.frames:
            raise RuntimeError("cannot attach timing before a frame trace exists")
        self.frames[-1].elapsed_ms = elapsed_ms

    def _load_entry_attempt(self) -> EntryMatchAttempt | None:
        connection = self.connection_factory()
        try:
            return EntryMatchAttemptRepository(connection).get(
                self.entry_attempt_id
            )
        finally:
            connection.close()

    @staticmethod
    def _apply_updates(
        projection: dict[str, object],
        updates: Sequence[object],
        *,
        id_attribute: str,
        category: str,
        changes: list[StateChange],
    ) -> None:
        for update in updates:
            scope_id = str(getattr(update, id_attribute))
            current_state = getattr(update, "state").value
            previous = projection.get(scope_id)
            previous_state = (
                None if previous is None else getattr(previous, "state").value
            )
            if previous_state != current_state:
                changes.append(
                    StateChange(
                        category=category,
                        scope_id=scope_id,
                        previous_state=previous_state,
                        current_state=current_state,
                    )
                )
            projection[scope_id] = update


def parse_entry_attempt_id(entry_attempt_id: UUID | str) -> EntryAttemptId:
    """현재 wire ``entryAttemptId``를 실제 domain identity로 변환한다."""

    return EntryAttemptId(
        entry_attempt_id
        if isinstance(entry_attempt_id, UUID)
        else UUID(entry_attempt_id)
    )


def _ordered_values(projection: dict[str, object]) -> tuple:
    return tuple(projection[key] for key in sorted(projection))
