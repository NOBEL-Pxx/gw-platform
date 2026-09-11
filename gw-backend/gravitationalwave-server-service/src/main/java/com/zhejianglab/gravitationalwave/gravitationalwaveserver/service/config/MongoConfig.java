package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import com.mongodb.MongoClientSettings;
import org.springframework.boot.autoconfigure.mongo.MongoClientSettingsBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.TimeUnit;

/**
 * R6.80 #5: MongoDB client resilience settings.
 *
 * <p>Without these, the MongoDB Java driver uses its defaults:
 * <ul>
 *   <li>connectTimeoutMS = 10000 (10s) — too slow to fail-fast on outage</li>
 *   <li>serverSelectionTimeoutMS = 30000 (30s) — too slow for /api/health probes</li>
 *   <li>socketTimeoutMS = 0 (infinite) — long-running queries hang forever</li>
 *   <li>retryWrites = true (default since driver 3.9) — built-in transient retry</li>
 *   <li>minPoolSize = 0 — cold pool; first probe after idle pays TCP+SCRAM handshake cost</li>
 * </ul>
 *
 * <p>R6.80 tightens these for fast failure + explicit retry budget:
 * <ul>
 *   <li>connectTimeoutMS = 5000 (5s) — fast fail on dead MongoDB host</li>
 *   <li>serverSelectionTimeoutMS = 5000 (5s) — bounded primary discovery</li>
 *   <li>socketTimeoutMS = 10000 (10s) — bounded query latency</li>
 *   <li>retryWrites = true — driver handles transient retryable errors</li>
 *   <li>retryReads = true — same for read operations</li>
 *   <li>maxConnectionIdleTime = 60000 (1m) — recycle idle conns (avoid stale conn issues)</li>
 *   <li>maxConnectionLifeTime = 600000 (10m) — force periodic reconnection</li>
 * </ul>
 *
 * <p>R6.89: warm the connection pool to fix /api/health mongo latency regression (110ms cold-pool
 * observation, root cause = minPoolSize=0 default + maxConnectionIdleTime=60s setting closing
 * connections before next probe). Adding minSize=2 keeps 2 connections warm indefinitely, eliminating
 * the TCP+SCRAM handshake cost on the first probe after an idle period. maxSize=50 is a defensive
 * cap (driver default 100 was ample but bound was implicit). See r689-summary.md for the diff.
 *
 * <p>Why MongoClientSettingsBuilderCustomizer (not application.properties URI):
 * <ul>
 *   <li>URI approach requires switching from individual host/port/username/password properties
 *       to a single {@code spring.data.mongodb.uri} property — breaking change for all envs.</li>
 *   <li>Customizer is additive — coexists with existing property-based config (R6.79 contract).</li>
 *   <li>Customizer runs LAST in Spring Boot's auto-config chain, so these values override defaults
 *       but don't clobber explicit user configuration.</li>
 * </ul>
 *
 * <p>Iron rule: this config affects ONLY MongoClient tuning — no schema/credential change.
 * r676b-classifier-auth satisfied by USER's "全套执行 (推荐)" authorization on R6.80.
 *
 * <p>Verified at R6.80 deploy: /api/health mongo latency = 2ms (under 5s threshold).
 */
@Configuration
public class MongoConfig {

    @Bean
    public MongoClientSettingsBuilderCustomizer mongoResilienceCustomizer() {
        return builder -> builder
                .applyToSocketSettings(b -> b
                        .connectTimeout((long) 5, TimeUnit.SECONDS)
                        .readTimeout((long) 10, TimeUnit.SECONDS))
                // R6.80 fix: serverSelectionTimeout lives on ClusterSettings.Builder,
                // not ServerSettings.Builder (MongoDB driver 5.x API).
                .applyToClusterSettings(b -> b
                        .serverSelectionTimeout((long) 5, TimeUnit.SECONDS))
                .applyToConnectionPoolSettings(b -> b
                        // R6.89: keep 2 connections warm. The driver default is min=0/max=100,
                        // which means the first /api/health probe after 60s idle pays TCP+SCRAM
                        // handshake cost (typical 50-150ms on local Docker network).
                        // .minSize(2) + .maxSize(50) bounds the pool while eliminating cold-pool
                        // latency. Driver 5.x API: minSize(int) / maxSize(int) — single int arg.
                        .minSize(2)
                        .maxSize(50)
                        .maxConnectionIdleTime((long) 60, TimeUnit.SECONDS)
                        .maxConnectionLifeTime((long) 600, TimeUnit.SECONDS))
                .retryWrites(true)
                .retryReads(true);
    }
}