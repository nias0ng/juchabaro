package com.ssafy.parking.domain.notification.entity;

import com.ssafy.parking.common.entity.BaseEntity;
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
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalTime;

@Getter
@Entity
@Table(name = "user_notification_settings")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class NotificationSetting extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "setting_id")
    private Long id;

    @OneToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_id", nullable = false, unique = true)
    private User user;

    @Column(name = "move_request_receive", nullable = false)
    private boolean moveRequestReceive;

    @Column(name = "response_reminder", nullable = false)
    private boolean responseReminder;

    @Column(name = "ev_overstay", nullable = false)
    private boolean evOverstay;

    @Column(name = "office_notice", nullable = false)
    private boolean officeNotice;

    @Column(name = "quiet_hours_start", nullable = false)
    private LocalTime quietHoursStart;

    @Column(name = "quiet_hours_end", nullable = false)
    private LocalTime quietHoursEnd;

    @Enumerated(EnumType.STRING)
    @Column(name = "channel", nullable = false, length = 20)
    private AlarmChannel channel;

    @Builder
    private NotificationSetting(
            User user,
            boolean moveRequestReceive,
            boolean responseReminder,
            boolean evOverstay,
            boolean officeNotice,
            LocalTime quietHoursStart,
            LocalTime quietHoursEnd,
            AlarmChannel channel
    ) {
        this.user = user;
        this.moveRequestReceive = moveRequestReceive;
        this.responseReminder = responseReminder;
        this.evOverstay = evOverstay;
        this.officeNotice = officeNotice;
        this.quietHoursStart = quietHoursStart;
        this.quietHoursEnd = quietHoursEnd;
        this.channel = channel;
    }

    public static NotificationSetting createDefault(User user) {
        return NotificationSetting.builder()
                .user(user)
                .moveRequestReceive(true)
                .responseReminder(true)
                .evOverstay(true)
                .officeNotice(false)
                .quietHoursStart(LocalTime.of(23, 0))
                .quietHoursEnd(LocalTime.of(7, 0))
                .channel(AlarmChannel.PUSH)
                .build();
    }

    // moveRequestReceive는 필수(항상 true)라 수정 대상 제외
    public void update(
            Boolean responseReminder,
            Boolean evOverstay,
            Boolean officeNotice,
            LocalTime quietHoursStart,
            LocalTime quietHoursEnd,
            AlarmChannel channel
    ) {
        if (responseReminder != null) this.responseReminder = responseReminder;
        if (evOverstay != null) this.evOverstay = evOverstay;
        if (officeNotice != null) this.officeNotice = officeNotice;
        if (quietHoursStart != null) this.quietHoursStart = quietHoursStart;
        if (quietHoursEnd != null) this.quietHoursEnd = quietHoursEnd;
        if (channel != null) this.channel = channel;
    }
}