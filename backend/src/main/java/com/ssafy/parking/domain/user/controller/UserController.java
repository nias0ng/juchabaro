package com.ssafy.parking.domain.user.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.user.dto.MeResponse;
import com.ssafy.parking.domain.user.service.UserService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.ssafy.parking.domain.user.dto.UpdateMeRequest;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@Tag(name = "사용자", description = "사용자 정보 API")
@RestController
@RequestMapping("/users")
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;

    @Operation(summary = "내 정보 조회", description = "인증된 사용자의 정보를 조회합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "조회 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보가 유효하지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "404", description = "사용자 정보를 찾을 수 없음")
    })
    @GetMapping("/me")
    public ResponseEntity<ApiResponse<MeResponse>> getMe(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId
    ) {
        MeResponse result = userService.getMe(userId);
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "내 정보 조회에 성공했습니다.", result)
        );
    }

    @Operation(summary = "내 정보 수정", description = "이름 또는 비밀번호를 수정합니다. 비밀번호 변경 시 현재 비밀번호가 필요합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "수정 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "요청 값 오류 / 현재 비밀번호 불일치"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보가 유효하지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "404", description = "사용자 정보를 찾을 수 없음")
    })
    @PatchMapping("/me")
    public ResponseEntity<ApiResponse<MeResponse>> updateMe(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId,
            @RequestBody UpdateMeRequest request
    ) {
        MeResponse result = userService.updateMe(userId, request);
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "회원 정보가 수정되었습니다.", result));
    }

    @Operation(summary = "회원 탈퇴", description = "계정을 탈퇴(비활성화) 처리합니다.")
    @SecurityRequirement(name = "bearerAuth")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "탈퇴 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "인증 정보가 유효하지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "404", description = "사용자 정보를 찾을 수 없음")
    })
    @PostMapping("/me/withdrawal")
    public ResponseEntity<ApiResponse<Void>> withdraw(
            @Parameter(hidden = true) @AuthenticationPrincipal Long userId
    ) {
        userService.withdraw(userId);
        return ResponseEntity.ok(ApiResponse.successWithoutData());
    }
}