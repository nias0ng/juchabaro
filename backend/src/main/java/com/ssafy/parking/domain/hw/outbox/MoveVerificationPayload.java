package com.ssafy.parking.domain.hw.outbox;

import java.time.OffsetDateTime;
import java.util.List;

public record MoveVerificationPayload(
        Long requestId,
        int verificationAttempt,
        List<String> targetIncidentIds,
        OffsetDateTime requestedAt,
        OffsetDateTime deadlineAt
) {}