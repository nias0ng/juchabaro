package com.ssafy.parking.domain.hw.dto;

import java.time.OffsetDateTime;

public record HwTransitionRequest(
        String parkingEpisodeId,
        Integer publicationRevision,
        String transitionType,      // PARKED | UNPARKED
        String physicalVehicleId,
        Long sessionId,
        OffsetDateTime occurredAt,
        Assignment assignment
) {
    public record Assignment(
            String state,           // ASSIGNED | AMBIGUOUS | UNASSIGNED
            Integer zoneId,         // = hw_zone_id (ASSIGNED일 때만)
            String unassignedReason
    ) {}
}