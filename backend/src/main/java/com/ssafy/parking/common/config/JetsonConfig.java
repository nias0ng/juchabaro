package com.ssafy.parking.common.config;

import com.ssafy.parking.domain.hw.outbox.JetsonClient;
import com.ssafy.parking.domain.hw.outbox.LoggingJetsonClient;
import com.ssafy.parking.domain.hw.outbox.RestClientJetsonClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import tools.jackson.databind.ObjectMapper;

@Configuration
public class JetsonConfig {

    @Bean
    public JetsonClient jetsonClient(
            @Value("${app.jetson.provider:log}") String provider,
            @Value("${app.jetson.base-url:http://e202:8000}") String baseUrl,
            @Value("${app.jetson.api-key:}") String apiKey,
            @Value("${app.jetson.timeout-ms:5000}") int timeoutMs,
            ObjectMapper objectMapper) {
        if ("real".equalsIgnoreCase(provider)) {
            return new RestClientJetsonClient(baseUrl, apiKey, timeoutMs, objectMapper);
        }
        return new LoggingJetsonClient();
    }
}