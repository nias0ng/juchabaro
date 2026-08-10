package com.ssafy.parking.domain.parking.dto;

import com.ssafy.parking.domain.parking.entity.ParkingZone;

import java.util.List;

public record ZoneListResponse(
        int totalCount,
        List<ZoneResponse> zones
) {
    public static ZoneListResponse from(List<ParkingZone> zones) {
        List<ZoneResponse> items = zones.stream().map(ZoneResponse::from).toList();
        return new ZoneListResponse(items.size(), items);
    }
}