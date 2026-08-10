package com.ssafy.parking.domain.move.dto;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;

public record MoveRequestSummaryResponse(
        Long requestId,
        Long eventId,
        Long requesterUserId,
        Long targetVehicleId,
        String targetPlateNumber,
        String requestType,
        String requestStatus,
        String eventType,
        String zoneNumber,
        String message,
        OffsetDateTime requestedAt,
        OffsetDateTime dueAt,
        OffsetDateTime resolvedAt,
        Integer estimatedMinutes,
        int reminderCount
) {
    public static MoveRequestSummaryResponse from(MoveRequest mr, Integer estimatedMinutes) {
        Long requesterUserId = (mr.getRequester() != null) ? mr.getRequester().getId() : null;
        ParkingEvent event = mr.getEvent();
        String zoneNumber = (event.getZone() != null) ? event.getZone().getZoneNumber() : null;
        OffsetDateTime resolvedAt = (event.getResolvedAt() != null) ? toKst(event.getResolvedAt()) : null;

        return new MoveRequestSummaryResponse(
                mr.getId(),
                event.getId(),
                requesterUserId,
                mr.getTargetVehicle().getId(),
                mr.getTargetVehicle().getPlateNumber(),
                mr.getRequestType().name(),
                mr.getRequestStatus().name(),
                event.getEventType().name(),
                zoneNumber,
                mr.getMessage(),
                toKst(mr.getRequestedAt()),
                (mr.getDueAt() != null) ? toKst(mr.getDueAt()) : null,
                resolvedAt,
                estimatedMinutes,
                mr.getReminderCount()
        );
    }

    private static OffsetDateTime toKst(LocalDateTime t) {
        return t.atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime();
    }
}