package com.ssafy.parking.domain.parking.dto;

import com.fasterxml.jackson.annotation.JsonRawValue;
import com.ssafy.parking.domain.parking.entity.ParkingZone;

public record ZoneResponse(
        Long zoneId,
        String zoneNumber,
        Integer hwZoneId,
        String zoneType,
        String entryExitRole,
        Integer allowedMinutes,
        String status,
        @JsonRawValue String geometry
) {
    public static ZoneResponse from(ParkingZone z) {
        return new ZoneResponse(
                z.getId(),
                z.getZoneNumber(),
                z.getHwZoneId(),
                z.getZoneType() != null ? z.getZoneType().name() : null,
                z.getEntryExitRole() != null ? z.getEntryExitRole().name() : null,
                z.getAllowedMinutes(),
                z.getStatus() != null ? z.getStatus().name() : null,
                z.getGeometryData()
        );
    }
}