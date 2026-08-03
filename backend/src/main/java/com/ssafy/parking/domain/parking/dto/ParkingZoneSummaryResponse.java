package com.ssafy.parking.domain.parking.dto;

import java.util.List;

public record ParkingZoneSummaryResponse(
        String floor,
        int totalSpots,
        int occupiedSpots,
        int availableSpots,
        int violationCount,
        int congestionRate,
        String congestionLevel,
        List<SpotResponse> spots
) {}