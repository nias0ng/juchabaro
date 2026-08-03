package com.ssafy.parking.domain.notification.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.notification.dto.NotificationSettingResponse;
import com.ssafy.parking.domain.notification.dto.NotificationSettingUpdateRequest;
import com.ssafy.parking.domain.notification.service.NotificationSettingService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "알림 설정", description = "사용자 알림 설정 API")
@RestController
@RequestMapping("/users/me/notification-settings")
@RequiredArgsConstructor
public class NotificationSettingController {

    private final NotificationSettingService notificationSettingService;

    @Operation(summary = "알림 설정 조회", description = "내 알림 설정을 조회합니다. 없으면 기본값으로 생성합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @GetMapping
    public ResponseEntity<ApiResponse<NotificationSettingResponse>> getSettings(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId
    ) {
        return ResponseEntity.ok(ApiResponse.success(
                HttpStatus.OK, "알림 설정 조회에 성공했습니다.",
                notificationSettingService.getSettings(userId)));
    }

    @Operation(summary = "알림 설정 수정", description = "토글/방해금지 시간/알림 방식을 부분 수정합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @PatchMapping
    public ResponseEntity<ApiResponse<NotificationSettingResponse>> updateSettings(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @RequestBody NotificationSettingUpdateRequest request
    ) {
        return ResponseEntity.ok(ApiResponse.success(
                HttpStatus.OK, "알림 설정이 수정되었습니다.",
                notificationSettingService.updateSettings(userId, request)));
    }
}