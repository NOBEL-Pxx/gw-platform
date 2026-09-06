package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.ApiException;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import jakarta.annotation.Resource;

@Component
public class RateLimitInterceptor implements HandlerInterceptor {

    @Resource
    private RateLimiter rateLimiter;

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response,
                             Object handler) throws Exception {
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return true;
        }

        String clientIp = getClientIp(request);
        if (rateLimiter.tryConsume(clientIp)) {
            return true;
        }

        long retryAfter = rateLimiter.getRefillSeconds();
        response.setHeader("Retry-After", String.valueOf(retryAfter));
        response.setHeader("X-RateLimit-Limit", String.valueOf(rateLimiter.getCapacity()));
        throw ApiException.tooManyRequests(
                String.format("Too many requests - retry after %ds", retryAfter));
    }

    private String getClientIp(HttpServletRequest request) {
        // Only trust X-Real-IP, which our nginx proxy overwrites from
        // $remote_addr (unspoofable). X-Forwarded-For is NOT set by nginx
        // for /api/ and is fully client-controlled — trusting it lets an
        // attacker rotate spoofed IPs to bypass rate limiting.
        String xRealIp = request.getHeader("X-Real-IP");
        if (xRealIp != null && !xRealIp.isBlank()) {
            return xRealIp.trim();
        }
        return request.getRemoteAddr();
    }
}
