package com.ssafy.parking.domain.hw.dto;

import java.time.OffsetDateTime;

public record HwIncidentTransitionRequest(
        String incidentId,
        Integer publicationRevision,
        String transitionType,          // OPEN | RESOLVE
        String physicalVehicleId,
        String entryAttemptId,
        Long sessionId,
        String ruleCode,
        Scope scope,
        Integer zoneId,                 // hw_zone_id
        String victimPhysicalVehicleId,
        OffsetDateTime firstObservedAt,
        OffsetDateTime occurredAt,
        String terminationReason
) {
    public record Scope(String type, String id) {}
}