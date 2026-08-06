package com.ssafy.parking.domain.parking.util;

import com.ssafy.parking.domain.parking.entity.ParkingEventType;

public final class RuleCodeMapper {
    private RuleCodeMapper() {}

    public static ParkingEventType toEventType(String ruleCode) {
        if (ruleCode == null) return ParkingEventType.ETC;
        return switch (ruleCode) {
            case "DISABLED_ZONE_UNAUTHORIZED", "DISABLED_ZONE_VIOLATION" -> ParkingEventType.DISABLED_ZONE_VIOLATION;
            case "EV_OVERSTAY" -> ParkingEventType.EV_OVERSTAY;
            case "BAD_PARKING" -> ParkingEventType.BAD_PARKING;
            case "DOUBLE_PARKING" -> ParkingEventType.DOUBLE_PARKING;
            case "OUT_OF_ZONE" -> ParkingEventType.OUT_OF_ZONE;
            // EV_ZONE_UNAUTHORIZED, AISLE_BLOCK, 기타 → ETC (팀 결정)
            default -> ParkingEventType.ETC;
        };
    }
}