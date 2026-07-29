package com.ssafy.parking.domain.vehicle.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import io.swagger.v3.oas.annotations.media.Schema;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;

public record VehicleDetailResponse(
        @Schema(example = "10") Long vehicleId,
        @Schema(example = "1") Long userId,
        @Schema(example = "12가3456") String plateNumber,
        @Schema(example = "아이오닉 5") String vehicleModel,
        @Schema(example = "false") @JsonProperty("isDisabledVehicle") boolean isDisabledVehicle,
        @Schema(example = "true") @JsonProperty("isElectric") boolean isElectric,
        @Schema(example = "RESIDENT") String ownerType,
        @Schema(example = "ACTIVE") String status,
        @Schema(example = "2026-07-23T14:10:00+09:00") OffsetDateTime createdAt,
        @Schema(example = "2026-07-23T14:10:00+09:00") OffsetDateTime updatedAt
) {
    public static VehicleDetailResponse from(Vehicle v) {
        return new VehicleDetailResponse(
                v.getId(), v.getUser().getId(), v.getPlateNumber(), v.getVehicleModel(),
                v.isDisabledVehicle(), v.isElectric(),
                v.getOwnerType().name(), v.getStatus().name(),
                toKst(v.getCreatedAt()), toKst(v.getUpdatedAt())
        );
    }

    private static OffsetDateTime toKst(LocalDateTime t) {
        return t.atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime();
    }
}