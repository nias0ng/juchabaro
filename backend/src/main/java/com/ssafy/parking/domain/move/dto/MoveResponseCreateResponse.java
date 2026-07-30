package com.ssafy.parking.domain.move.dto;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.entity.MoveRequestResponse;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;

public record MoveResponseCreateResponse(
        Long responseId,
        Long requestId,
        String responseType,
        Integer estimatedMinutes,
        String requestStatus,
        String eventStatus,
        int reminderCount,
        OffsetDateTime dueAt,
        OffsetDateTime respondedAt
) {
    public static MoveResponseCreateResponse from(MoveRequestResponse response, MoveRequest mr, ParkingEvent event) {
        return new MoveResponseCreateResponse(
                response.getId(),
                mr.getId(),
                response.getResponseType().name(),
                response.getEstimatedMinutes(),
                mr.getRequestStatus().name(),
                event.getEventStatus().name(),
                mr.getReminderCount(),
                (mr.getDueAt() != null) ? toKst(mr.getDueAt()) : null,
                toKst(response.getRespondedAt())
        );
    }

    private static OffsetDateTime toKst(LocalDateTime t) {
        return t.atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime();
    }
}