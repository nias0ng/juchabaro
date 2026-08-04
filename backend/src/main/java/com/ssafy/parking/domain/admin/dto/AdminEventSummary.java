package com.ssafy.parking.domain.admin.dto;

import java.time.OffsetDateTime;

public record AdminEventSummary(
        Long eventId,
        String plateNumber,
        String eventType,
        String requestStatus,   // 연결된 이동요청 상태(없으면 null)
        String zoneNumber,
        OffsetDateTime detectedAt,
        Integer violationRatio,
        String eventStatus
) {}