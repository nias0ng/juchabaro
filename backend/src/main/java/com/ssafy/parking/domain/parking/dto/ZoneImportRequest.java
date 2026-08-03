package com.ssafy.parking.domain.parking.dto;

import com.ssafy.parking.domain.parking.entity.EntryExitRole;
import com.ssafy.parking.domain.parking.entity.ParkingZoneType;

import java.util.List;

public record ZoneImportRequest(
        Integer zoneDefinitionVersion,
        String calibrationReference,
        List<ZoneItem> zones
) {
    public record ZoneItem(
            Integer zoneId,                  // → hw_zone_id
            ParkingZoneType zoneType,
            EntryExitRole entryExitRole,     // nullable
            Integer allowedDurationSeconds,  // nullable
            List<List<Double>> polygon,
            String chargerClass,             // nullable
            List<Integer> egressZoneIds      // nullable
    ) {}
}