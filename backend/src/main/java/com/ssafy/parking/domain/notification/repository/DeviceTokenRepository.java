package com.ssafy.parking.domain.notification.repository;

import com.ssafy.parking.domain.notification.entity.DeviceToken;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface DeviceTokenRepository extends JpaRepository<DeviceToken, Long> {
    Optional<DeviceToken> findByToken(String token);
    List<DeviceToken> findByUser_Id(Long userId);
    void deleteByUser_IdAndToken(Long userId, String token);
    void deleteByToken(String token);
}