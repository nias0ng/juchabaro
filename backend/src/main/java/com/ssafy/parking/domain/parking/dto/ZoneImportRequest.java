package com.ssafy.parking.domain.parking.dto;

import com.ssafy.parking.domain.parking.entity.EntryExitRole;
import com.ssafy.parking.domain.parking.entity.ParkingZoneType;

import java.util.List;

public record ZoneImportRequest(
        Integer zoneDefinitionVersion,
        String calibrationReference,
        String floor,
        List<ZoneItem> zones
) {
    public record ZoneItem(
            Integer zoneId,
            ParkingZoneType zoneType,
            EntryExitRole entryExitRole,
            Integer allowedDurationSeconds,
            List<List<Double>> polygon,
            String chargerClass,
            List<Integer> egressZoneIds
    ) {}
}