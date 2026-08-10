package com.ssafy.parking.domain.parking.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.parking.dto.ParkingSessionListResponse;
import com.ssafy.parking.domain.parking.service.ParkingStatusService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "주차 세션", description = "주차 세션 조회 API")
@RestController
@RequestMapping("/parking-sessions")
@RequiredArgsConstructor
public class ParkingSessionController {

    private final ParkingStatusService parkingStatusService;

    @Operation(summary = "내 주차 세션 조회", description = "로그인 사용자 소유 차량의 현재 주차 세션을 조회합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @GetMapping("/me")
    public ResponseEntity<ApiResponse<ParkingSessionListResponse>> getMySessions(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId
    ) {
        return ResponseEntity.ok(ApiResponse.success(
                HttpStatus.OK, "주차 세션 조회에 성공했습니다.",
                parkingStatusService.getMySessions(userId)));
    }
}