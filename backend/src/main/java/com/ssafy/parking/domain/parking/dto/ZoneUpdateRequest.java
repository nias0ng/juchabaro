package com.ssafy.parking.domain.parking.dto;

import com.ssafy.parking.domain.parking.entity.ParkingZoneType;

public record ZoneUpdateRequest(
        String zoneNumber,
        ParkingZoneType zoneType,
        Integer allowedMinutes
) {}