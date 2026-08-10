package com.ssafy.parking.domain.hw.dto;

import java.time.OffsetDateTime;
import java.util.List;

public record MoveVerificationResultRequest(
        Integer verificationAttempt,
        Integer publicationRevision,
        String result,                    // RESOLVED | STILL_ACTIVE | UNKNOWN
        List<IncidentResult> incidentResults,
        OffsetDateTime completedAt
) {
    public record IncidentResult(
            String incidentId,
            String result,                // RESOLVED | STILL_ACTIVE | UNKNOWN
            Integer incidentPublicationRevision
    ) {}
}