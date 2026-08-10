package com.ssafy.parking.domain.notification.service;

import com.ssafy.parking.domain.notification.dto.NotificationSettingResponse;
import com.ssafy.parking.domain.notification.dto.NotificationSettingUpdateRequest;
import com.ssafy.parking.domain.notification.entity.NotificationSetting;
import com.ssafy.parking.domain.notification.repository.NotificationSettingRepository;
import com.ssafy.parking.domain.user.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalTime;

@Service
@RequiredArgsConstructor
public class NotificationSettingService {

    private final NotificationSettingRepository notificationSettingRepository;
    private final UserRepository userRepository;

    @Transactional
    public NotificationSettingResponse getSettings(Long userId) {
        return NotificationSettingResponse.from(getOrCreate(userId));
    }

    @Transactional
    public NotificationSettingResponse updateSettings(Long userId, NotificationSettingUpdateRequest request) {
        NotificationSetting setting = getOrCreate(userId);
        setting.update(
                request.responseReminder(),
                request.evOverstay(),
                request.officeNotice(),
                parseTime(request.quietHoursStart()),
                parseTime(request.quietHoursEnd()),
                request.channel()
        );
        return NotificationSettingResponse.from(setting);
    }

    // 최초 조회 시 기본값으로 생성
    private NotificationSetting getOrCreate(Long userId) {
        return notificationSettingRepository.findByUser_Id(userId)
                .orElseGet(() -> notificationSettingRepository.save(
                        NotificationSetting.createDefault(userRepository.getReferenceById(userId))));
    }

    private LocalTime parseTime(String hhmm) {
        return (hhmm != null && !hhmm.isBlank()) ? LocalTime.parse(hhmm) : null;
    }
}