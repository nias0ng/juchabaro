package com.ssafy.parking.domain.notification.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.notification.dto.NotificationDetailResponse;
import com.ssafy.parking.domain.notification.dto.NotificationListResponse;
import com.ssafy.parking.domain.notification.entity.Notification;
import com.ssafy.parking.domain.notification.entity.NotificationType;
import com.ssafy.parking.domain.notification.repository.NotificationRepository;
import com.ssafy.parking.domain.parking.entity.EventImage;
import com.ssafy.parking.domain.parking.repository.EventImageRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@RequiredArgsConstructor
public class NotificationService {

    private final NotificationRepository notificationRepository;
    private final EventImageRepository eventImageRepository;

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

    @Transactional(readOnly = true)
    public NotificationDetailResponse getNotification(Long userId, Long notificationId) {
        Notification notification = notificationRepository.findById(notificationId)
                .orElseThrow(() -> new BusinessException(ErrorCode.NOTIFICATION_NOT_FOUND));
        if (!notification.getUser().getId().equals(userId)) {
            throw new BusinessException(ErrorCode.NOTIFICATION_ACCESS_DENIED);
        }

        List<EventImage> images = (notification.getEvent() != null)
                ? eventImageRepository.findByEvent_Id(notification.getEvent().getId())
                : List.of();

        return NotificationDetailResponse.from(notification, images);
    }
}