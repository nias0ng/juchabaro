package com.ssafy.parking.domain.parking.dto;

import com.fasterxml.jackson.annotation.JsonRawValue;

public record SpotResponse(
        Long zoneId,
        String zoneNumber,
        String zoneType,
        @JsonRawValue String geometryData,
        String occupancyStatus
) {}