package com.ssafy.parking.domain.vehicle.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.ssafy.parking.domain.vehicle.entity.VehicleOwnerType;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.time.LocalDate;

public record VehicleCreateRequest(
        @Schema(description = "차량 번호", example = "12가3456")
        @NotBlank(message = "차량 등록 요청 값이 올바르지 않습니다.")
        String plateNumber,

        @Schema(description = "차종/모델 (RESIDENT만)", example = "아이오닉 5")
        String vehicleModel,

        @Schema(description = "장애인 등록 차량 여부", example = "false")
        @JsonProperty("isDisabledVehicle")
        @NotNull(message = "차량 등록 요청 값이 올바르지 않습니다.")
        Boolean isDisabledVehicle,

        @Schema(description = "전기차 여부", example = "true")
        @JsonProperty("isElectric")
        @NotNull(message = "차량 등록 요청 값이 올바르지 않습니다.")
        Boolean isElectric,

        @Schema(description = "소유 유형", example = "RESIDENT")
        @NotNull(message = "차량 등록 요청 값이 올바르지 않습니다.")
        VehicleOwnerType ownerType,

        @Schema(description = "방문일 (VISITOR만)", example = "2026-07-27")
        LocalDate visitDate
) {}