package com.ssafy.parking.domain.hw.dto;

import java.time.OffsetDateTime;

public record HwExitRequest(
        Long sessionId,
        Integer publicationRevision,
        String physicalVehicleId,
        OffsetDateTime occurredAt,
        String origin,             // JETSON_EXIT_CONFIRMED
        String evidence            // FULL_AREA_ABSENCE 등
) {}