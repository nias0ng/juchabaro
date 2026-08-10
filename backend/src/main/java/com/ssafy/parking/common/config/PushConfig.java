package com.ssafy.parking.common.config;

import com.ssafy.parking.domain.notification.push.ExpoPushSender;
import com.ssafy.parking.domain.notification.push.LoggingPushSender;
import com.ssafy.parking.domain.notification.push.PushSender;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class PushConfig {

    @Bean
    public PushSender pushSender(
            @Value("${app.push.provider:log}") String provider,
            @Value("${app.push.expo.url:https://exp.host/--/api/v2/push/send}") String expoUrl) {
        if ("expo".equalsIgnoreCase(provider)) {
            return new ExpoPushSender(expoUrl);
        }
        return new LoggingPushSender();
    }
}