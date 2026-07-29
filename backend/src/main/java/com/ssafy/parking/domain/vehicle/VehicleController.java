package com.ssafy.parking.domain.vehicle.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.vehicle.dto.VehicleCreateRequest;
import com.ssafy.parking.domain.vehicle.dto.VehicleCreateResponse;
import com.ssafy.parking.domain.vehicle.service.VehicleService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "차량", description = "차량 등록 API")
@RestController
@RequestMapping("/vehicles")
@RequiredArgsConstructor
public class VehicleController {

    private final VehicleService vehicleService;

    @Operation(summary = "차량 등록", description = "인증된 사용자가 차량을 등록합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "201", description = "등록 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "요청 값 오류"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보 유효하지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "409", description = "이미 등록된 차량 번호")
    })
    @PostMapping
    public ResponseEntity<ApiResponse<VehicleCreateResponse>> register(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @Valid @RequestBody VehicleCreateRequest request
    ) {
        VehicleCreateResponse result = vehicleService.register(userId, request);
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success(HttpStatus.CREATED, "차량이 등록되었습니다.", result));
    }
}