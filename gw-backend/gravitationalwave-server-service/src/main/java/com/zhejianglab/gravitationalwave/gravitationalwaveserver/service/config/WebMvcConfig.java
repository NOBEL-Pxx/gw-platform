package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import jakarta.annotation.Resource;

@Configuration
@EnableScheduling
public class WebMvcConfig implements WebMvcConfigurer {

    @Resource
    private RateLimitInterceptor rateLimitInterceptor;

    @Resource
    private AuthInterceptor authInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // Rate limit runs FIRST — applies to /api/** + /static-files/** (v4.16)
        // R6.85c: REMOVED excludePathPatterns("/api/health") — /api/health is now rate-limited
        // at the default 60/min/IP bucket (rate.limit.capacity). Auth still excludes it (public).
        // R6.85c motivation: closes R6.80 L5 deferred (rate-limit /api/health for abuse prevention).
        registry.addInterceptor(rateLimitInterceptor)
                .addPathPatterns("/api/**", "/static-files/**");

        // Auth runs SECOND — enforces JWT on protected paths
        // /api/health remains public (no auth required, per R6.80 health endpoint design)
        registry.addInterceptor(authInterceptor)
                .addPathPatterns("/api/**")
                .excludePathPatterns("/api/auth/login", "/api/auth/register", "/api/auth/refresh", "/api/health");
    }
}