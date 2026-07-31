package com.ssafy.parking.domain.move.dto;

import com.ssafy.parking.domain.move.entity.MoveRequest;

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
        String message,
        OffsetDateTime requestedAt,
        OffsetDateTime dueAt,
        int reminderCount
) {
    public static MoveRequestSummaryResponse from(MoveRequest mr) {
        Long requesterUserId = (mr.getRequester() != null) ? mr.getRequester().getId() : null;
        return new MoveRequestSummaryResponse(
                mr.getId(),
                mr.getEvent().getId(),
                requesterUserId,
                mr.getTargetVehicle().getId(),
                mr.getTargetVehicle().getPlateNumber(),
                mr.getRequestType().name(),
                mr.getRequestStatus().name(),
                mr.getEvent().getEventType().name(),
                mr.getMessage(),
                toKst(mr.getRequestedAt()),
                (mr.getDueAt() != null) ? toKst(mr.getDueAt()) : null,
                mr.getReminderCount()
        );
    }

    private static OffsetDateTime toKst(LocalDateTime t) {
        return t.atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime();
    }
}