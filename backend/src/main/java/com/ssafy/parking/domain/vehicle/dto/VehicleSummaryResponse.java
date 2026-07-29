package com.ssafy.parking.domain.vehicle.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import io.swagger.v3.oas.annotations.media.Schema;

public record VehicleSummaryResponse(
        @Schema(example = "10") Long vehicleId,
        @Schema(example = "12가3456") String plateNumber,
        @Schema(example = "아이오닉 5") String vehicleModel,
        @Schema(example = "false") @JsonProperty("isDisabledVehicle") boolean isDisabledVehicle,
        @Schema(example = "true") @JsonProperty("isElectric") boolean isElectric,
        @Schema(example = "RESIDENT") String ownerType,
        @Schema(example = "ACTIVE") String status
) {
    public static VehicleSummaryResponse from(Vehicle v) {
        return new VehicleSummaryResponse(
                v.getId(), v.getPlateNumber(), v.getVehicleModel(),
                v.isDisabledVehicle(), v.isElectric(),
                v.getOwnerType().name(), v.getStatus().name()
        );
    }
}