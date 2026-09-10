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
        // R6.103: exclude /api/health from rate limit so external monitoring can poll freely
        registry.addInterceptor(rateLimitInterceptor)
                .addPathPatterns("/api/**", "/static-files/**")
                .excludePathPatterns("/api/health");

        // Auth runs SECOND — enforces JWT on protected paths
        // R6.103: also exclude /api/health (public health endpoint, no auth)
        registry.addInterceptor(authInterceptor)
                .addPathPatterns("/api/**")
                .excludePathPatterns("/api/auth/login", "/api/auth/register", "/api/auth/refresh", "/api/health");
    }
}