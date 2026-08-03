package com.ssafy.parking.domain.user.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.common.security.JwtTokenProvider;
import com.ssafy.parking.domain.user.dto.*;
import com.ssafy.parking.domain.user.entity.User;
import com.ssafy.parking.domain.user.entity.UserRole;
import com.ssafy.parking.domain.user.entity.UserStatus;
import com.ssafy.parking.domain.user.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;

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

    @Transactional(readOnly = true)
    public MeResponse getMe(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException(ErrorCode.USER_NOT_FOUND));
        return MeResponse.from(user);
    }

    @Transactional
    public MeResponse updateMe(Long userId, UpdateMeRequest request) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException(ErrorCode.USER_NOT_FOUND));

        boolean hasName = request.name() != null && !request.name().isBlank();
        boolean hasNewPassword = request.newPassword() != null && !request.newPassword().isBlank();

        if (!hasName && !hasNewPassword) {
            throw new BusinessException(ErrorCode.USER_UPDATE_INVALID);
        }

        if (hasName) {
            user.changeName(request.name());
        }

        if (hasNewPassword) {
            if (request.currentPassword() == null
                    || !passwordEncoder.matches(request.currentPassword(), user.getPasswordHash())) {
                throw new BusinessException(ErrorCode.CURRENT_PASSWORD_MISMATCH);
            }
            user.changePassword(passwordEncoder.encode(request.newPassword()));
        }

        return MeResponse.from(user);
    }

    @Transactional
    public WithdrawalResponse withdraw(Long userId, WithdrawalRequest request) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException(ErrorCode.USER_NOT_FOUND));

        if (request.currentPassword() == null
                || !passwordEncoder.matches(request.currentPassword(), user.getPasswordHash())) {
            throw new BusinessException(ErrorCode.CURRENT_PASSWORD_MISMATCH);
        }

        user.withdraw(); // status = DELETED
        OffsetDateTime withdrawnAt = LocalDateTime.now()
                .atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime();
        return new WithdrawalResponse(user.getId(), user.getStatus().name(), withdrawnAt);
    }
}