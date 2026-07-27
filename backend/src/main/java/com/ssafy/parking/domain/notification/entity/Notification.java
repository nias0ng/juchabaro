package com.ssafy.parking.domain.notification.entity;

import com.ssafy.parking.common.entity.BaseCreatedEntity;
import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.user.entity.User;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Getter
@Entity
@Table(name = "notifications")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Notification extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "notification_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "event_id")
    private ParkingEvent event;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "request_id")
    private MoveRequest request;

    @Enumerated(EnumType.STRING)
    @Column(name = "notification_type", nullable = false, length = 30)
    private NotificationType notificationType;

    @Column(name = "title", nullable = false, length = 100)
    private String title;

    @Column(name = "body", nullable = false, columnDefinition = "TEXT")
    private String body;

    @Column(name = "sent_at", nullable = false)
    private LocalDateTime sentAt;

    @Builder
    private Notification(
            User user,
            ParkingEvent event,
            MoveRequest request,
            NotificationType notificationType,
            String title,
            String body,
            LocalDateTime sentAt
    ) {
        this.user = user;
        this.event = event;
        this.request = request;
        this.notificationType = notificationType;
        this.title = title;
        this.body = body;
        this.sentAt = sentAt;
    }
}