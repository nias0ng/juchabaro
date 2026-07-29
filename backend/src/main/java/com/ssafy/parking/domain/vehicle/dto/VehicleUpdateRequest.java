package com.ssafy.parking.domain.vehicle.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.ssafy.parking.domain.vehicle.entity.VehicleOwnerType;
import io.swagger.v3.oas.annotations.media.Schema;

public record VehicleUpdateRequest(
        @Schema(example = "12가3456") String plateNumber,
        @Schema(example = "아이오닉 5 N") String vehicleModel,
        @Schema(example = "false") @JsonProperty("isDisabledVehicle") Boolean isDisabledVehicle,
        @Schema(example = "true") @JsonProperty("isElectric") Boolean isElectric,
        @Schema(example = "RESIDENT") VehicleOwnerType ownerType
) {
    public boolean isEmpty() {
        return plateNumber == null && vehicleModel == null
                && isDisabledVehicle == null && isElectric == null && ownerType == null;
    }
}