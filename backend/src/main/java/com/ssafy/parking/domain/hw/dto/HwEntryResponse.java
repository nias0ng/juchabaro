package com.ssafy.parking.domain.hw.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;

public record HwEntryResponse(
        String accessDecision,
        boolean registered,
        Long vehicleId,
        @JsonProperty("isDisabledVehicle") Boolean isDisabledVehicle,
        @JsonProperty("isElectric") Boolean isElectric,
        String vehicleStatus,
        String trackingId,
        Long sessionId,
        boolean duplicateRequest
) {
    public static HwEntryResponse matched(AccessDecision decision, Vehicle v,
                                          String trackingId, Long sessionId, boolean duplicate) {
        return new HwEntryResponse(
                decision.name(), true, v.getId(),
                v.isDisabledVehicle(), v.isElectric(), v.getStatus().name(),
                trackingId, sessionId, duplicate);
    }

    public static HwEntryResponse denied(String trackingId) {
        return new HwEntryResponse(
                AccessDecision.DENY.name(), false, null, null, null, null,
                trackingId, null, false);
    }
}