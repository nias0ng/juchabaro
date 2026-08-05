package com.ssafy.parking.domain.hw.outbox;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.OffsetDateTime;

public record SessionContextUpdatePayload(
        Long sessionId,
        String entryAttemptId,
        int contextRevision,
        String administrativeState,   // ACTIVE | CLOSED
        OffsetDateTime updatedAt,
        SessionContext sessionContext
) {
    public record SessionContext(
            Long vehicleId,
            @JsonProperty("isDisabledVehicle") boolean isDisabledVehicle,
            @JsonProperty("isElectric") boolean isElectric
    ) {}
}