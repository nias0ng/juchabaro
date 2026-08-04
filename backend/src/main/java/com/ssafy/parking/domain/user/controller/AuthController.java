package com.ssafy.parking.domain.user.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.notification.service.DeviceTokenService;
import com.ssafy.parking.domain.user.dto.*;
import com.ssafy.parking.domain.user.service.UserService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "인증", description = "회원가입 / 로그인 API")
@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
public class AuthController {

    private final UserService userService;
    private final DeviceTokenService deviceTokenService;

    @Operation(summary = "회원가입", description = "신규 사용자를 등록합니다. 로그인 아이디는 중복될 수 없습니다.")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "201", description = "회원가입 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "요청 값이 올바르지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "409", description = "이미 사용 중인 로그인 아이디")
    })
    @PostMapping("/signup")
    public ResponseEntity<ApiResponse<SignupResponse>> signup(
            @Valid @RequestBody SignupRequest request
    ) {
        SignupResponse result = userService.signup(request);
        return ResponseEntity
                .status(HttpStatus.CREATED)
                .body(ApiResponse.success(HttpStatus.CREATED, "회원가입이 완료되었습니다.", result));
    }

    @Operation(summary = "로그인", description = "로그인에 성공하면 JWT 액세스 토큰을 발급합니다.")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "로그인 성공"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "요청 값이 올바르지 않음"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "아이디 또는 비밀번호 불일치"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "403", description = "사용할 수 없는 계정")
    })
    @PostMapping("/login")
    public ResponseEntity<ApiResponse<LoginResponse>> login(
            @Valid @RequestBody LoginRequest request
    ) {
        LoginResponse result = userService.login(request);
        return ResponseEntity.ok(
                ApiResponse.success(HttpStatus.OK, "로그인에 성공했습니다.", result)
        );
    }

    @Operation(summary = "로그아웃", description = "Stateless JWT — 클라이언트가 토큰을 폐기하고, 전달된 기기 토큰이 있으면 제거합니다.")
    @PostMapping("/logout")
    public ResponseEntity<ApiResponse<Void>> logout(
            @RequestBody(required = false) LogoutRequest request) {
        if (request != null) {
            deviceTokenService.unregisterByToken(request.token());
        }
        return ResponseEntity.ok(ApiResponse.successWithoutData());
    }
}