package com.ssafy.parking.domain.move.entity;

import com.ssafy.parking.common.entity.BaseEntity;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.user.entity.User;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
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
@Table(name = "move_requests")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class MoveRequest extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "request_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "event_id", nullable = false)
    private ParkingEvent event;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "requester_user_id")
    private User requester;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "target_vehicle_id", nullable = false)
    private Vehicle targetVehicle;

    @Enumerated(EnumType.STRING)
    @Column(name = "request_type", nullable = false, length = 20)
    private MoveRequestType requestType;

    @Enumerated(EnumType.STRING)
    @Column(name = "request_status", nullable = false, length = 30)
    private MoveRequestStatus requestStatus;

    @Column(name = "message", columnDefinition = "TEXT")
    private String message;

    @Column(name = "requested_at", nullable = false)
    private LocalDateTime requestedAt;

    @Column(name = "due_at")
    private LocalDateTime dueAt;

    @Column(name = "reminder_count", nullable = false)
    private int reminderCount;

    @Column(name = "reminder_sent_at")
    private LocalDateTime reminderSentAt;

    @Builder
    private MoveRequest(
            ParkingEvent event,
            User requester,
            Vehicle targetVehicle,
            MoveRequestType requestType,
            MoveRequestStatus requestStatus,
            String message,
            LocalDateTime requestedAt,
            LocalDateTime dueAt
    ) {
        this.event = event;
        this.requester = requester;
        this.targetVehicle = targetVehicle;
        this.requestType = requestType;
        this.requestStatus = requestStatus;
        this.message = message;
        this.requestedAt = requestedAt;
        this.dueAt = dueAt;
        this.reminderCount = 0;
    }

    public void markResponded(java.time.LocalDateTime dueAt) {
        this.requestStatus = MoveRequestStatus.RESPONDED;
        this.dueAt = dueAt;
    }

    public void markNeedAdmin() {
        this.requestStatus = MoveRequestStatus.NEED_ADMIN;
        this.dueAt = null;
    }

    public void markReminderSent(LocalDateTime reminderSentAt) {
        this.requestStatus = MoveRequestStatus.REMINDER_SENT;
        this.reminderCount = this.reminderCount + 1;
        this.reminderSentAt = reminderSentAt;
    }

    public void markCompleted() {
        this.requestStatus = MoveRequestStatus.COMPLETED;
    }
}