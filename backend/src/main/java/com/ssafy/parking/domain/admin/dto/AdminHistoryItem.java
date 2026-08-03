package com.ssafy.parking.domain.admin.dto;

import java.time.OffsetDateTime;

public record AdminHistoryItem(
        Long logId, Long eventId, String plateNumber,
        String actionType, String adminName, OffsetDateTime actedAt, String memo
) {}