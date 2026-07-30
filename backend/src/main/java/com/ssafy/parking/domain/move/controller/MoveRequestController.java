package com.ssafy.parking.domain.move.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.move.dto.MoveRequestCreateResponse;
import com.ssafy.parking.domain.move.service.MoveRequestService;
import com.ssafy.parking.domain.parking.entity.ParkingEventType;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

@Tag(name = "이동 요청", description = "차량 이동 요청 API")
@RestController
@RequestMapping("/move-requests")
@RequiredArgsConstructor
public class MoveRequestController {

    private final MoveRequestService moveRequestService;

    @Operation(summary = "차량 이동 요청(수동 신고)", description = "잘못 주차된 차량에 이동을 요청합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "201", description = "요청 전송 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "요청 값 오류"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보 유효하지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "404", description = "대상 차량 주차 정보 없음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "409", description = "이미 처리 중인 요청 존재")
    })
    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<ApiResponse<MoveRequestCreateResponse>> create(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @RequestParam(required = false) String targetPlateNumber,
            @RequestParam(required = false) ParkingEventType eventType,
            @RequestParam(required = false) String reason,
            @RequestParam(required = false) Long zoneId,
            @RequestPart(value = "images", required = false) List<MultipartFile> images
    ) {
        MoveRequestCreateResponse result =
                moveRequestService.create(userId, targetPlateNumber, eventType, reason, zoneId, images);
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success(HttpStatus.CREATED, "차량 이동 요청이 전송되었습니다.", result));
    }
}