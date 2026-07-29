package com.ssafy.parking.domain.vehicle.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.vehicle.dto.*;
import com.ssafy.parking.domain.vehicle.entity.VehicleOwnerType;
import com.ssafy.parking.domain.vehicle.entity.VehicleStatus;
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
import org.springframework.web.bind.annotation.*;

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

    @Operation(summary = "차량 목록 조회", description = "내가 등록한 차량 목록을 조회합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "조회 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "필터 값 오류"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보 유효하지 않음")
    })
    @GetMapping
    public ResponseEntity<ApiResponse<VehicleListResponse>> getMyVehicles(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @RequestParam(required = false) VehicleOwnerType ownerType,
            @RequestParam(required = false) VehicleStatus status
    ) {
        VehicleListResponse result = vehicleService.getMyVehicles(userId, ownerType, status);
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "차량 목록 조회에 성공했습니다.", result));
    }

    @Operation(summary = "차량 상세 조회", description = "본인이 등록한 차량의 상세 정보를 조회합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "조회 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보 유효하지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "403", description = "접근 권한 없음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "404", description = "차량 없음")
    })
    @GetMapping("/{vehicleId}")
    public ResponseEntity<ApiResponse<VehicleDetailResponse>> getVehicle(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @PathVariable Long vehicleId
    ) {
        VehicleDetailResponse result = vehicleService.getVehicle(userId, vehicleId);
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "차량 상세 조회에 성공했습니다.", result));
    }

    @Operation(summary = "차량 수정", description = "본인 차량의 정보를 부분 수정합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "수정 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "수정 필드 없음/값 오류"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보 유효하지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "403", description = "수정 권한 없음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "404", description = "차량 없음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "409", description = "차량 번호 중복")
    })
    @PatchMapping("/{vehicleId}")
    public ResponseEntity<ApiResponse<VehicleUpdateResponse>> update(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @PathVariable Long vehicleId,
            @RequestBody VehicleUpdateRequest request
    ) {
        VehicleUpdateResponse result = vehicleService.update(userId, vehicleId, request);
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "차량 정보가 수정되었습니다.", result));
    }

    @Operation(summary = "차량 삭제", description = "본인 차량을 소프트 삭제합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "삭제 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보 유효하지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "403", description = "삭제 권한 없음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "404", description = "차량 없음/이미 삭제됨"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "409", description = "처리 중 주차 기록 존재")
    })
    @DeleteMapping("/{vehicleId}")
    public ResponseEntity<ApiResponse<VehicleDeleteResponse>> delete(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @PathVariable Long vehicleId
    ) {
        VehicleDeleteResponse result = vehicleService.delete(userId, vehicleId);
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "차량 등록이 삭제되었습니다.", result));
    }
}