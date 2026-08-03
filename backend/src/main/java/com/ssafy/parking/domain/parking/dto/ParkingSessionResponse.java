package com.ssafy.parking.domain.parking.dto;

import com.ssafy.parking.domain.parking.entity.ParkingSession;
import com.ssafy.parking.domain.parking.entity.ParkingZone;

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
        String floor,
        OffsetDateTime enteredAt
) {
    public static ParkingSessionResponse of(ParkingSession s, boolean violation) {
        ParkingZone zone = s.getZone();
        return new ParkingSessionResponse(
                s.getId(),
                s.getVehicle().getId(),
                s.getVehicle().getPlateNumber(),
                violation ? "VIOLATION" : "PARKED",
                (zone != null) ? zone.getId() : null,
                (zone != null) ? zone.getZoneNumber() : null,
                (zone != null) ? zone.getFloor() : null,
                toKst(s.getEntryTime())
        );
    }

    private static OffsetDateTime toKst(LocalDateTime t) {
        return t.atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime();
    }
}