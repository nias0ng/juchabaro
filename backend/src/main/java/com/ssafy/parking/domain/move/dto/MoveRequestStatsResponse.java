package com.ssafy.parking.domain.move.dto;

public record MoveRequestStatsResponse(
        int totalCount,
        int unresolvedCount,
        int averageResponseMinutes
) {}