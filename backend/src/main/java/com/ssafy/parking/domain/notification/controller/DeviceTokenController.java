package com.ssafy.parking.domain.notification.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.notification.dto.DeviceTokenRequest;
import com.ssafy.parking.domain.notification.service.DeviceTokenService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@Tag(name = "디바이스 토큰", description = "푸시 알림용 기기 토큰 등록/해제")
@SecurityRequirement(name = "bearerAuth")
@RestController
@RequestMapping("/users/me/device-tokens")
@RequiredArgsConstructor
public class DeviceTokenController {

    private final DeviceTokenService deviceTokenService;

    @Operation(summary = "디바이스 토큰 등록", description = "Expo/FCM push token을 등록합니다(중복 시 갱신).")
    @PostMapping
    public ResponseEntity<ApiResponse<Void>> register(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @Valid @RequestBody DeviceTokenRequest request
    ) {
        deviceTokenService.register(userId, request.token(), request.platform());
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success(HttpStatus.CREATED, "디바이스 토큰이 등록되었습니다.", null));
    }

    @Operation(summary = "디바이스 토큰 해제", description = "로그아웃 시 해당 기기 토큰을 제거합니다.")
    @DeleteMapping
    public ResponseEntity<ApiResponse<Void>> unregister(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @Valid @RequestBody DeviceTokenRequest request
    ) {
        deviceTokenService.unregister(userId, request.token());
        return ResponseEntity.ok(ApiResponse.successWithoutData());
    }
}