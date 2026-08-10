package com.ssafy.parking.domain.notification.push;

import java.util.List;
import java.util.Map;

public interface PushSender {
    void send(List<String> tokens, String title, String body, Map<String, Object> data);
}