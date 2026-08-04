package com.ssafy.parking.domain.notification.push;

import lombok.extern.slf4j.Slf4j;

import java.util.List;
import java.util.Map;

@Slf4j
public class LoggingPushSender implements PushSender {
    @Override
    public void send(List<String> tokens, String title, String body, Map<String, Object> data) {
        log.info("[PUSH:log] tokens={} title=\"{}\" body=\"{}\" data={}",
                tokens == null ? 0 : tokens.size(), title, body, data);
    }
}