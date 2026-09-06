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
        registry.addInterceptor(rateLimitInterceptor)
                .addPathPatterns("/api/**", "/static-files/**");

        // Auth runs SECOND — enforces JWT on protected paths
        registry.addInterceptor(authInterceptor)
                .addPathPatterns("/api/**")
                .excludePathPatterns("/api/auth/login", "/api/auth/register", "/api/auth/refresh");
    }
}
