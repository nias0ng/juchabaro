package com.ssafy.parking.domain.parking.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.parking.dto.*;
import com.ssafy.parking.domain.parking.service.ZoneService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@Tag(name = "주차 구역", description = "주차 구역(zone) 카탈로그 및 정의 관리 API")
@RestController
@RequestMapping("/zones")
@RequiredArgsConstructor
public class ZoneController {

    private final ZoneService zoneService;

    @Operation(summary = "구역 목록 조회", description = "등록된 모든 주차 구역을 반환합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @GetMapping
    public ResponseEntity<ApiResponse<ZoneListResponse>> getZones() {
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "구역 목록 조회에 성공했습니다.", zoneService.getZones()));
    }

    // TODO: ADMIN 권한으로 제한 필요 (현재는 인증된 사용자면 호출 가능)
    @Operation(summary = "구역 정의 import", description = "HW zone_definition JSON을 받아 upsert합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @PostMapping("/import")
    public ResponseEntity<ApiResponse<ZoneImportResult>> importZones(
            @RequestBody ZoneImportRequest request
    ) {
        ZoneImportResult result = zoneService.importZones(request);
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "구역 정의를 반영했습니다.", result));
    }

    @Operation(summary = "구역 수정", description = "관리자가 구역 번호/유형/허용시간을 부분 수정합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @PatchMapping("/{zoneId}")
    public ResponseEntity<ApiResponse<ZoneResponse>> updateZone(
            @PathVariable Long zoneId,
            @RequestBody ZoneUpdateRequest request) {
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "구역을 수정했습니다.",
                zoneService.updateZone(zoneId, request)));
    }
}