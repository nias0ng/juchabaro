package com.ssafy.parking.domain.hw.outbox;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.OffsetDateTime;

public record EntryReviewResolutionPayload(
        String entryAttemptId,
        int decisionRevision,
        String resolution,            // REVIEW_ALLOW | REVIEW_DENY | REVIEW_EXPIRED
        OffsetDateTime resolvedAt,
        SessionContext sessionContext // REVIEW_ALLOW만 값, 그 외 null
) {
    public record SessionContext(
            Long sessionId,
            Long vehicleId,
            @JsonProperty("isDisabledVehicle") boolean isDisabledVehicle,
            @JsonProperty("isElectric") boolean isElectric
    ) {}
}