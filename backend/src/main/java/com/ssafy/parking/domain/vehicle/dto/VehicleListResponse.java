package com.ssafy.parking.domain.vehicle.dto;

import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;

public record VehicleListResponse(
        @Schema(example = "1") int totalCount,
        List<VehicleSummaryResponse> vehicles
) {
    public static VehicleListResponse from(List<Vehicle> vehicles) {
        List<VehicleSummaryResponse> items = vehicles.stream()
                .map(VehicleSummaryResponse::from)
                .toList();
        return new VehicleListResponse(items.size(), items);
    }
}