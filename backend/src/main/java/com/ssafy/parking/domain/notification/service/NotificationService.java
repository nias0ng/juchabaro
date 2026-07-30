package com.ssafy.parking.domain.notification.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.notification.dto.NotificationListResponse;
import com.ssafy.parking.domain.notification.entity.Notification;
import com.ssafy.parking.domain.notification.entity.NotificationType;
import com.ssafy.parking.domain.notification.repository.NotificationRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class NotificationService {

    private final NotificationRepository notificationRepository;

    @Transactional(readOnly = true)
    public NotificationListResponse getNotifications(
            Long userId, NotificationType type, int page, int size
    ) {
        if (page < 0 || size < 1) {
            throw new BusinessException(ErrorCode.NOTIFICATION_QUERY_INVALID);
        }
        Pageable pageable = PageRequest.of(page, size, Sort.by(Sort.Direction.DESC, "sentAt"));
        Page<Notification> result = notificationRepository.findByUser(userId, type, pageable);
        return NotificationListResponse.from(result);
    }
}