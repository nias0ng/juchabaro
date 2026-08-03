package com.ssafy.parking.domain.hw.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.hw.dto.HwPublicationAck;
import com.ssafy.parking.domain.hw.dto.MoveVerificationResultRequest;
import com.ssafy.parking.domain.hw.service.HwMoveVerificationService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "HW-이동확인", description = "Jetson 이동 재확인 결과 API (X-HW-API-Key)")
@SecurityRequirement(name = "hwApiKey")
@RestController
@RequestMapping("/hw/move-requests")
@RequiredArgsConstructor
public class HwMoveVerificationController {

    private final HwMoveVerificationService hwMoveVerificationService;

    @Operation(summary = "이동 재확인 결과", description = "Jetson 현장 재확인 결과를 받아 이동요청 상태에 반영합니다.")
    @PostMapping("/{requestId}/verification")
    public ResponseEntity<ApiResponse<HwPublicationAck>> verification(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @PathVariable Long requestId,
            @RequestBody MoveVerificationResultRequest request
    ) {
        HwPublicationAck ack = hwMoveVerificationService.handle(requestId, request);
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "재확인 결과가 반영되었습니다.", ack));
    }
}