package com.ssafy.parking.domain.admin.dto;

import java.time.OffsetDateTime;
import java.util.List;

public record AdminEventDetailResponse(
        Long eventId,
        String plateNumber,
        String eventType,
        String eventStatus,
        String requestType,
        String requestStatus,
        String zoneNumber,
        String floor,
        OffsetDateTime detectedAt,
        OffsetDateTime resolvedAt,
        String reason,
        Integer reminderCount,
        OffsetDateTime requestedAt,
        List<Image> images,
        List<Response> responses,
        List<ActionLog> actionLogs
) {
    public record Image(Long imageId, String imageUrl, OffsetDateTime capturedAt) {}
    public record Response(String responseType, Integer estimatedMinutes, OffsetDateTime respondedAt) {}
    public record ActionLog(Long logId, String actionType, String adminName, OffsetDateTime actedAt, String memo) {}
}