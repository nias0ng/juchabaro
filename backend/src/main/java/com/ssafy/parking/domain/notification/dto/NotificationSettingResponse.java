package com.ssafy.parking.domain.notification.dto;

import com.ssafy.parking.domain.notification.entity.NotificationSetting;

import java.time.format.DateTimeFormatter;

public record NotificationSettingResponse(
        boolean moveRequestReceive,
        boolean responseReminder,
        boolean evOverstay,
        boolean officeNotice,
        String quietHoursStart,
        String quietHoursEnd,
        String channel
) {
    private static final DateTimeFormatter HHMM = DateTimeFormatter.ofPattern("HH:mm");

    public static NotificationSettingResponse from(NotificationSetting s) {
        return new NotificationSettingResponse(
                s.isMoveRequestReceive(),
                s.isResponseReminder(),
                s.isEvOverstay(),
                s.isOfficeNotice(),
                s.getQuietHoursStart().format(HHMM),
                s.getQuietHoursEnd().format(HHMM),
                s.getChannel().name()
        );
    }
}