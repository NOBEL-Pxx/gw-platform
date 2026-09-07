package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

/**
 * R6.72 #3: Log app.version on ApplicationReadyEvent.
 *
 * Reads app.version from version.properties (generated at Maven build time
 * by groovy-maven-plugin in start/pom.xml via `git describe --tags --long --dirty`).
 *
 * Mirrors the frontend's src/version.ts (R6.71 #4) — both backend and frontend
 * log the same git describe string, so support tickets can correlate frontend
 * bundle version with backend API version.
 *
 * Why this matters:
 *   - Frontend Sentry already gets APP_VERSION via vite.config.ts define:
 *   - Backend has no version visibility — Docker image tag is just `latest`
 *   - When user reports "X endpoint returns 500", we need to know which commit
 *     was running. This listener writes `app.version=v4.62+R6.71-5-g225dd92` to
 *     startup log + structured log fields.
 *
 * Fallback chain:
 *   1. version.properties (set by groovy-maven-plugin during mvn package)
 *   2. env var APP_VERSION (set by CI/deploy.yml from ${{ github.ref_name }})
 *   3. hardcoded 'unknown' (never expected in production)
 */
@Component
public class StartupVersionLogger {

    private static final Logger log = LoggerFactory.getLogger(StartupVersionLogger.class);

    private final Environment env;

    public StartupVersionLogger(Environment env) {
        this.env = env;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void logVersion() {
        String version = env.getProperty("app.version");
        if (version == null || version.isBlank()) {
            version = System.getenv("APP_VERSION");
        }
        if (version == null || version.isBlank()) {
            version = "unknown";
        }
        String activeProfiles = String.join(",", env.getActiveProfiles());
        log.info("==========================================================");
        log.info("  GravitationalWave backend starting");
        log.info("  app.version = {}", version);
        log.info("  active profiles = [{}]", activeProfiles.isEmpty() ? "(default)" : activeProfiles);
        log.info("  spring.application.name = {}", env.getProperty("spring.application.name", "(unset)"));
        log.info("  server.port = {}", env.getProperty("server.port", "(unset)"));
        log.info("==========================================================");
    }
}
