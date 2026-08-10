package com.ssafy.parking.domain.notification.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.notification.entity.DeviceToken;
import com.ssafy.parking.domain.notification.repository.DeviceTokenRepository;
import com.ssafy.parking.domain.user.entity.User;
import com.ssafy.parking.domain.user.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class DeviceTokenService {

    private final DeviceTokenRepository deviceTokenRepository;
    private final UserRepository userRepository;

    @Transactional
    public void register(Long userId, String token, String platform) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException(ErrorCode.USER_NOT_FOUND));
        deviceTokenRepository.findByToken(token).ifPresentOrElse(
                dt -> dt.rebind(user, platform),
                () -> deviceTokenRepository.save(DeviceToken.builder()
                        .user(user).token(token).platform(platform).build()));
    }

    @Transactional
    public void unregister(Long userId, String token) {
        deviceTokenRepository.deleteByUser_IdAndToken(userId, token);
    }

    @Transactional
    public void unregisterByToken(String token) {
        if (token != null && !token.isBlank()) {
            deviceTokenRepository.deleteByToken(token);
        }
    }
}