package com.ssafy.parking.domain.notification.dto;

import com.ssafy.parking.domain.notification.entity.AlarmChannel;

public record NotificationSettingUpdateRequest(
        Boolean responseReminder,
        Boolean evOverstay,
        Boolean officeNotice,
        String quietHoursStart,
        String quietHoursEnd,
        AlarmChannel channel
) {}