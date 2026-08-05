package com.ssafy.parking.domain.admin.dto;

import java.time.OffsetDateTime;

public record AdminEventSummary(
        Long eventId,
        String plateNumber,
        String eventType,
        String requestType,      // AUTO | MANUAL (연결 이동요청 없으면 null)
        String requestStatus,    // 연결 이동요청 없으면 null
        String zoneNumber,
        OffsetDateTime detectedAt,
        String eventStatus
) {}