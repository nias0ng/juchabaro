package com.ssafy.parking.domain.hw.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.hw.dto.HwEntryRequest;
import com.ssafy.parking.domain.hw.dto.HwEntryResponse;
import com.ssafy.parking.domain.hw.service.HwEntryService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "HW-입차", description = "라즈베리파이 입차 판정 API (X-HW-API-Key 인증)")
@RestController
@RequestMapping("/hw/parking")
@RequiredArgsConstructor
public class HwController {

    private final HwEntryService hwEntryService;

    @Operation(summary = "입차 판정 + 세션 생성", description = "OCR 번호를 등록차량과 매칭해 ALLOW/REVIEW/DENY 판정")
    @PostMapping("/entry")
    public ResponseEntity<ApiResponse<HwEntryResponse>> entry(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @Valid @RequestBody HwEntryRequest request
    ) {
        HwEntryResponse result = hwEntryService.processEntry(idempotencyKey, request);

        boolean newAllow = "ALLOW".equals(result.accessDecision()) && !result.duplicateRequest();
        HttpStatus status = newAllow ? HttpStatus.CREATED : HttpStatus.OK;
        String message = switch (result.accessDecision()) {
            case "ALLOW" -> result.duplicateRequest() ? "이미 처리된 요청입니다." : "입차가 허용되었습니다.";
            case "REVIEW" -> "차량 확인이 필요합니다.";
            default -> "입차가 거부되었습니다.";
        };
        return ResponseEntity.status(status)
                .body(ApiResponse.success(status, message, result));
    }
}