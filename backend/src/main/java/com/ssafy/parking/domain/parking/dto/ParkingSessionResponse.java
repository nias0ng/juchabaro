package com.ssafy.parking.domain.parking.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.ssafy.parking.domain.parking.entity.ParkingSession;
import com.ssafy.parking.domain.parking.entity.ParkingZone;
import com.ssafy.parking.domain.parking.entity.ParkingZoneType;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;

public record ParkingSessionResponse(
        Long sessionId,
        Long vehicleId,
        String plateNumber,
        String status,
        Long zoneId,
        String zoneNumber,
        String zoneType,                                  // 신규: GENERAL/DISABLED/EV_CHARGING (미배정 null)
        String floor,
        OffsetDateTime enteredAt,
        @JsonProperty("isElectric") boolean isElectric,   // 신규
        OffsetDateTime dueAt                              // 신규: EV 충전구역 주차 시 parkedAt + 허용시간
) {
    public static ParkingSessionResponse of(ParkingSession s, boolean violation) {
        ParkingZone zone = s.getZone();

        OffsetDateTime dueAt = null;
        if (zone != null
                && zone.getZoneType() == ParkingZoneType.EV_CHARGING
                && s.getParkedAt() != null
                && zone.getAllowedMinutes() != null) {
            dueAt = toKst(s.getParkedAt().plusMinutes(zone.getAllowedMinutes()));
        }

        return new ParkingSessionResponse(
                s.getId(),
                s.getVehicle().getId(),
                s.getVehicle().getPlateNumber(),
                violation ? "VIOLATION" : "PARKED",
                (zone != null) ? zone.getId() : null,
                (zone != null) ? zone.getZoneNumber() : null,
                (zone != null) ? zone.getZoneType().name() : null,
                (zone != null) ? zone.getFloor() : null,
                toKst(s.getEntryTime()),
                s.getVehicle().isElectric(),
                dueAt
        );
    }

    private static OffsetDateTime toKst(LocalDateTime t) {
        return t.atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime();
    }
}