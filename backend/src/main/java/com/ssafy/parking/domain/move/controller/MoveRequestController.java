package com.ssafy.parking.domain.move.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.move.dto.MoveRequestCreateResponse;
import com.ssafy.parking.domain.move.dto.MoveRequestListResponse;
import com.ssafy.parking.domain.move.entity.MoveRequestScope;
import com.ssafy.parking.domain.move.entity.MoveRequestStatus;
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

import com.ssafy.parking.domain.move.dto.MoveRequestDetailResponse;
import com.ssafy.parking.domain.move.dto.MoveResponseCreateRequest;
import com.ssafy.parking.domain.move.dto.MoveResponseCreateResponse;

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
            @RequestParam(required = false) String zoneName,
            @RequestPart(value = "images", required = false) List<MultipartFile> images
    ) {
        MoveRequestCreateResponse result =
                moveRequestService.create(userId, targetPlateNumber, eventType, reason, zoneName, images);
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success(HttpStatus.CREATED, "차량 이동 요청이 전송되었습니다.", result));
    }

    @Operation(summary = "이동 요청 목록 조회", description = "받은/보낸 이동 요청을 페이지로 조회합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "조회 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "조회 조건 오류"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보 유효하지 않음")
    })
    @GetMapping
    public ResponseEntity<ApiResponse<MoveRequestListResponse>> getMoveRequests(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @RequestParam(defaultValue = "ALL") MoveRequestScope scope,
            @RequestParam(required = false) MoveRequestStatus requestStatus,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size
    ) {
        MoveRequestListResponse result =
                moveRequestService.getMoveRequests(userId, scope, requestStatus, page, size);
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "이동 요청 목록 조회에 성공했습니다.", result));
    }

    @Operation(summary = "이동 요청 상세 조회", description = "요청자 또는 대상 차주가 이동 요청 상세를 조회합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "조회 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보 유효하지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "403", description = "접근 권한 없음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "404", description = "이동 요청 없음")
    })
    @GetMapping("/{requestId}")
    public ResponseEntity<ApiResponse<MoveRequestDetailResponse>> getMoveRequest(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @PathVariable Long requestId
    ) {
        MoveRequestDetailResponse result = moveRequestService.getMoveRequest(userId, requestId);
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "이동 요청 상세 조회에 성공했습니다.", result));
    }

    @Operation(summary = "이동 요청 응답(원탭)", description = "대상 차주가 이동 예정/불가로 응답합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "201", description = "응답 등록 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "응답 값 오류"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보 유효하지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "403", description = "응답 권한 없음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "404", description = "이동 요청 없음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "409", description = "응답 불가 상태")
    })
    @PostMapping("/{requestId}/responses")
    public ResponseEntity<ApiResponse<MoveResponseCreateResponse>> respond(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @PathVariable Long requestId,
            @RequestBody MoveResponseCreateRequest request
    ) {
        MoveResponseCreateResponse result = moveRequestService.respond(userId, requestId, request);
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success(HttpStatus.CREATED, "이동 요청 응답이 등록되었습니다.", result));
    }
}