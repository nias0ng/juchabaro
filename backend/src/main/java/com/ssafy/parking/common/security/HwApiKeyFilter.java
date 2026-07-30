package com.ssafy.parking.common.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Component
public class HwApiKeyFilter extends OncePerRequestFilter {

    private static final String HEADER = "X-HW-API-Key";
    private final String apiKey;

    public HwApiKeyFilter(@Value("${app.hw.api-key}") String apiKey) {
        this.apiKey = apiKey;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        // /hw/** 경로만 API 키 검증
        if (request.getRequestURI().startsWith("/hw/")) {
            String key = request.getHeader(HEADER);
            if (key == null || !key.equals(apiKey)) {
                response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                response.setContentType("application/json;charset=UTF-8");
                response.getWriter().write(
                        "{\"httpStatus\":\"UNAUTHORIZED\",\"isSuccess\":false," +
                                "\"message\":\"HW 인증 정보가 유효하지 않습니다.\",\"code\":401,\"result\":null}");
                return;
            }
        }
        filterChain.doFilter(request, response);
    }
}