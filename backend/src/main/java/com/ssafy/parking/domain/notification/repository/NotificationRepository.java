package com.ssafy.parking.domain.notification.repository;

import com.ssafy.parking.domain.notification.entity.Notification;
import org.springframework.data.jpa.repository.JpaRepository;

public interface NotificationRepository extends JpaRepository<Notification, Long> {
}