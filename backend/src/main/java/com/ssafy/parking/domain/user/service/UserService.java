package com.ssafy.parking.domain.user.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.common.security.JwtTokenProvider;
import com.ssafy.parking.domain.user.dto.LoginRequest;
import com.ssafy.parking.domain.user.dto.LoginResponse;
import com.ssafy.parking.domain.user.dto.SignupRequest;
import com.ssafy.parking.domain.user.dto.SignupResponse;
import com.ssafy.parking.domain.user.entity.User;
import com.ssafy.parking.domain.user.entity.UserRole;
import com.ssafy.parking.domain.user.entity.UserStatus;
import com.ssafy.parking.domain.user.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class UserService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenProvider jwtTokenProvider;

    @Transactional
    public SignupResponse signup(SignupRequest request) {
        if (userRepository.existsByLoginId(request.loginId())) {
            throw new BusinessException(ErrorCode.DUPLICATE_LOGIN_ID);
        }

        User user = User.builder()
                .loginId(request.loginId())
                .passwordHash(passwordEncoder.encode(request.password()))
                .phoneNumber(request.phoneNumber())
                .buildingNumber(request.buildingNumber())
                .unitNumber(request.unitNumber())
                .name(request.name())
                .role(UserRole.RESIDENT)
                .status(UserStatus.ACTIVE)
                .build();

        userRepository.save(user);
        return SignupResponse.from(user);
    }

    @Transactional(readOnly = true)
    public LoginResponse login(LoginRequest request) {
        User user = userRepository.findByLoginId(request.loginId())
                .orElseThrow(() -> new BusinessException(ErrorCode.INVALID_CREDENTIALS));

        if (!passwordEncoder.matches(request.password(), user.getPasswordHash())) {
            throw new BusinessException(ErrorCode.INVALID_CREDENTIALS);
        }

        if (user.getStatus() == UserStatus.SUSPENDED || user.getStatus() == UserStatus.DELETED) {
            throw new BusinessException(ErrorCode.ACCOUNT_DISABLED);
        }

        String accessToken = jwtTokenProvider.createAccessToken(user.getId(), user.getRole().name());
        return new LoginResponse(
                accessToken,
                "Bearer",
                jwtTokenProvider.getAccessTokenValiditySeconds(),
                user.getId(),
                user.getName(),
                user.getRole().name()
        );
    }
}