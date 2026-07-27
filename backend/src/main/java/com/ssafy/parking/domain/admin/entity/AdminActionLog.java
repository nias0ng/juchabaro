package com.ssafy.parking.domain.admin.entity;

import com.ssafy.parking.common.entity.BaseCreatedEntity;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
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

@Getter
@Entity
@Table(name = "admin_action_logs")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class AdminActionLog extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "action_log_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "admin_user_id", nullable = false)
    private User adminUser;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "event_id", nullable = false)
    private ParkingEvent event;

    @Column(name = "action_type", nullable = false, length = 40)
    private String actionType;

    @Enumerated(EnumType.STRING)
    @Column(name = "before_status", length = 30)
    private ParkingEventStatus beforeStatus;

    @Enumerated(EnumType.STRING)
    @Column(name = "after_status", length = 30)
    private ParkingEventStatus afterStatus;

    @Column(name = "memo", columnDefinition = "TEXT")
    private String memo;

    @Builder
    private AdminActionLog(
            User adminUser,
            ParkingEvent event,
            String actionType,
            ParkingEventStatus beforeStatus,
            ParkingEventStatus afterStatus,
            String memo
    ) {
        this.adminUser = adminUser;
        this.event = event;
        this.actionType = actionType;
        this.beforeStatus = beforeStatus;
        this.afterStatus = afterStatus;
        this.memo = memo;
    }
}