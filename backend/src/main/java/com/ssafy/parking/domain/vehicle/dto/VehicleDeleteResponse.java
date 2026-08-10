package com.ssafy.parking.domain.vehicle.dto;

import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import io.swagger.v3.oas.annotations.media.Schema;

import java.time.OffsetDateTime;
import java.time.ZoneId;

public record VehicleDeleteResponse(
        @Schema(example = "10") Long vehicleId,
        @Schema(example = "DELETED") String status,
        @Schema(example = "2026-07-23T14:40:00+09:00") OffsetDateTime updatedAt
) {
    public static VehicleDeleteResponse from(Vehicle v) {
        return new VehicleDeleteResponse(
                v.getId(), v.getStatus().name(),
                v.getUpdatedAt().atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime()
        );
    }
}