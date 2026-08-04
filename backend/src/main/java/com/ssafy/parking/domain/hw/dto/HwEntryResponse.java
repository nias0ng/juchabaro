package com.ssafy.parking.domain.hw.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonInclude(JsonInclude.Include.ALWAYS)
public record HwEntryResponse(
        String accessDecision,          // ALLOW | REVIEW | DENY
        String entryAttemptId,
        int decisionRevision,
        boolean duplicateRequest,
        SessionContext sessionContext   // ALLOW만 값, REVIEW/DENY는 null
) {
    public record SessionContext(
            Long sessionId,
            Long vehicleId,
            @JsonProperty("isDisabledVehicle") boolean isDisabledVehicle,
            @JsonProperty("isElectric") boolean isElectric
    ) {}
}