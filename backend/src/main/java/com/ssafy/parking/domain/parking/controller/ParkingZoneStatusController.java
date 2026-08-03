package com.ssafy.parking.domain.parking.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.parking.dto.ParkingZoneSummaryResponse;
import com.ssafy.parking.domain.parking.service.ParkingStatusService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "주차 구역 현황", description = "주차 구역 집계/점유 현황 API")
@RestController
@RequestMapping("/parking-zones")
@RequiredArgsConstructor
public class ParkingZoneStatusController {

    private final ParkingStatusService parkingStatusService;

    @Operation(summary = "구역 현황 조회", description = "층 기준 주차면 점유/위반/혼잡도와 면별 상태를 반환합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @GetMapping("/summary")
    public ResponseEntity<ApiResponse<ParkingZoneSummaryResponse>> getSummary() {
        return ResponseEntity.ok(ApiResponse.success(
                HttpStatus.OK, "구역 현황 조회에 성공했습니다.",
                parkingStatusService.getSummary()));
    }
}