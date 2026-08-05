package com.ssafy.parking.domain.notification.service;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.notification.entity.*;
import com.ssafy.parking.domain.notification.push.PushSender;
import com.ssafy.parking.domain.notification.repository.DeviceTokenRepository;
import com.ssafy.parking.domain.notification.repository.NotificationRepository;
import com.ssafy.parking.domain.notification.repository.NotificationSettingRepository;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.user.entity.User;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class NotificationDispatcher {

    private final NotificationRepository notificationRepository;
    private final NotificationSettingRepository notificationSettingRepository;
    private final DeviceTokenRepository deviceTokenRepository;
    private final PushSender pushSender;

    @Transactional
    public Notification dispatch(User user, NotificationType type, String title, String body,
                                 ParkingEvent event, MoveRequest request, LocalDateTime sentAt) {
        // 1) 인앱 알림 저장 (설정과 무관하게 항상 기록)
        Notification notification = notificationRepository.save(Notification.builder()
                .user(user).event(event).request(request)
                .notificationType(type).title(title).body(body).sentAt(sentAt)
                .build());

        // 2) 설정 확인 (없으면 기본=발송)
        NotificationSetting setting = notificationSettingRepository.findByUser_Id(user.getId()).orElse(null);
        if (setting != null) {
            if (!typeEnabled(setting, type)) return notification;            // 타입 토글 off
            if (isQuiet(sentAt.toLocalTime(), setting.getQuietHoursStart(), setting.getQuietHoursEnd())) {
                return notification;                                         // 방해 금지 시간 → 인앱만
            }
            if (setting.getChannel() == AlarmChannel.PUSH_SMS) {
                log.debug("PUSH_SMS 채널 - SMS 발송은 후속 구현, 현재는 PUSH만");
            }
        }

        // 3) 푸시 발송 (외부 실패가 트랜잭션/알림저장을 깨지 않도록 격리)
        List<String> tokens = deviceTokenRepository.findByUser_Id(user.getId())
                .stream().map(DeviceToken::getToken).toList();
        if (!tokens.isEmpty()) {
            Map<String, Object> data = new HashMap<>();
            data.put("type", type.name());
            data.put("notificationId", notification.getId());
            if (event != null) data.put("eventId", event.getId());
            if (request != null) data.put("requestId", request.getId());
            try {
                pushSender.send(tokens, title, body, data);
            } catch (Exception e) {
                log.warn("푸시 발송 실패(알림 저장은 유지): userId={}, type={}", user.getId(), type, e);
            }
        }
        return notification;
    }

    private boolean typeEnabled(NotificationSetting s, NotificationType t) {
        return switch (t) {
            case MOVE_REQUEST -> s.isMoveRequestReceive();
            case REMINDER -> s.isResponseReminder();
            case EV_OVERSTAY -> s.isEvOverstay();
            case MOVE_RESPONSE, EVENT_RESOLVED -> true;
        };
    }

    private boolean isQuiet(LocalTime now, LocalTime start, LocalTime end) {
        if (start == null || end == null || start.equals(end)) return false;
        if (start.isBefore(end)) return !now.isBefore(start) && now.isBefore(end);
        return !now.isBefore(start) || now.isBefore(end);   // 자정 넘어가는 구간(23:00~07:00)
    }
}