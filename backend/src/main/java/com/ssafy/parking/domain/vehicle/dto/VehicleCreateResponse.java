package com.ssafy.parking.domain.vehicle.dto;

import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import io.swagger.v3.oas.annotations.media.Schema;

import java.time.LocalDate;

public record VehicleCreateResponse(
        @Schema(description = "생성된 차량 ID", example = "10") Long vehicleId,
        @Schema(description = "등록 사용자 ID", example = "1") Long userId,
        @Schema(description = "차량 번호", example = "12가3456") String plateNumber,
        @Schema(description = "소유 유형", example = "RESIDENT") String ownerType,
        @Schema(description = "차량 상태", example = "ACTIVE") String status,
        @Schema(description = "방문일 (VISITOR만 반환)", example = "2026-07-27") LocalDate visitDate
) {
    public static VehicleCreateResponse from(Vehicle vehicle, Long userId) {
        return new VehicleCreateResponse(
                vehicle.getId(),
                userId,
                vehicle.getPlateNumber(),
                vehicle.getOwnerType().name(),
                vehicle.getStatus().name(),
                vehicle.getVisitDate()
        );
    }
}