package com.ssafy.parking.domain.admin.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.admin.dto.*;
import com.ssafy.parking.domain.admin.service.AdminEventService;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
import com.ssafy.parking.domain.parking.entity.ParkingEventType;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;

@Tag(name = "관리자-사건", description = "관리자 웹 사건/이력 관리 API (ADMIN 전용)")
@SecurityRequirement(name = "bearerAuth")
@RestController
@RequestMapping("/admin/parking-events")
@RequiredArgsConstructor
public class AdminEventController {

    private final AdminEventService adminEventService;

    @Operation(summary = "사건 목록 조회")
    @GetMapping
    public ResponseEntity<ApiResponse<AdminEventListResponse>> list(
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam(required = false) ParkingEventStatus eventStatus,
            @RequestParam(required = false) ParkingEventType eventType,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "사건 목록 조회에 성공했습니다.",
                adminEventService.getEvents(date, eventStatus, eventType, page, size)));
    }

    @Operation(summary = "처리 이력 조회")
    @GetMapping("/history")
    public ResponseEntity<ApiResponse<AdminHistoryResponse>> history(
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate startDate,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate endDate,
            @RequestParam(required = false) String actionType,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "처리 이력 조회에 성공했습니다.",
                adminEventService.getHistory(startDate, endDate, actionType, page, size)));
    }

    @Operation(summary = "사건 상세 조회")
    @GetMapping("/{eventId}")
    public ResponseEntity<ApiResponse<AdminEventDetailResponse>> detail(@PathVariable Long eventId) {
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "사건 상세 조회에 성공했습니다.",
                adminEventService.getEvent(eventId)));
    }

    @Operation(summary = "완료 처리")
    @PostMapping("/{eventId}/complete")
    public ResponseEntity<ApiResponse<Void>> complete(
            @Parameter(hidden = true) @AuthenticationPrincipal Long adminId,
            @PathVariable Long eventId, @RequestBody AdminActionRequest request) {
        adminEventService.complete(eventId, adminId, request.memo());
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "완료 처리되었습니다.", null));
    }

    @Operation(summary = "오탐 처리")
    @PostMapping("/{eventId}/dismiss")
    public ResponseEntity<ApiResponse<Void>> dismiss(
            @Parameter(hidden = true) @AuthenticationPrincipal Long adminId,
            @PathVariable Long eventId, @RequestBody AdminActionRequest request) {
        adminEventService.dismiss(eventId, adminId, request.memo());
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "오탐 처리되었습니다.", null));
    }

    @Operation(summary = "관리자 확인")
    @PostMapping("/{eventId}/acknowledge")
    public ResponseEntity<ApiResponse<Void>> acknowledge(
            @Parameter(hidden = true) @AuthenticationPrincipal Long adminId,
            @PathVariable Long eventId, @RequestBody AdminActionRequest request) {
        adminEventService.acknowledge(eventId, adminId, request.memo());
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "확인 처리되었습니다.", null));
    }

    @Operation(summary = "재알림 전송")
    @PostMapping("/{eventId}/reminders")
    public ResponseEntity<ApiResponse<Void>> remind(
            @Parameter(hidden = true) @AuthenticationPrincipal Long adminId,
            @PathVariable Long eventId) {
        adminEventService.sendReminder(eventId, adminId);
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "재알림을 전송했습니다.", null));
    }
}