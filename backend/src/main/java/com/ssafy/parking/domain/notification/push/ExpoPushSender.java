package com.ssafy.parking.domain.notification.push;

import org.springframework.http.MediaType;
import org.springframework.web.client.RestClient;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class ExpoPushSender implements PushSender {

    private final String url;
    private final RestClient client;

    public ExpoPushSender(String url) {
        this.url = url;
        this.client = RestClient.create();
    }

    @Override
    public void send(List<String> tokens, String title, String body, Map<String, Object> data) {
        if (tokens == null || tokens.isEmpty()) return;
        List<Map<String, Object>> messages = new ArrayList<>();
        for (String t : tokens) {
            Map<String, Object> m = new HashMap<>();
            m.put("to", t);
            m.put("title", title);
            m.put("body", body);
            if (data != null) m.put("data", data);
            messages.add(m);
        }
        client.post().uri(url)
                .contentType(MediaType.APPLICATION_JSON)
                .body(messages)
                .retrieve()
                .toBodilessEntity();
    }
}