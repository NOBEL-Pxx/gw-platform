package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import io.github.bucket4j.Refill;
import io.github.bucket4j.distributed.proxy.ProxyManager;
import io.github.bucket4j.distributed.proxy.RecoveryStrategy;
import io.github.bucket4j.redis.lettuce.cas.LettuceBasedProxyManager;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.api.StatefulRedisConnection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

import java.time.Duration;

/**
 * R6.53 #3: Distributed rate limiter backed by Redis (via Bucket4j Lettuce proxy).
 * Activated by Spring profile "redis" — requires Redis server reachable + bucket4j-redis
 * on classpath (declared optional in pom.xml so this class is only loaded when present).
 *
 * To enable on zjlab or prod:
 *   1. Set spring.profiles.active=redis (or include "redis" in SPRING_PROFILES_ACTIVE)
 *   2. Set rate.limit.redis-uri=redis://10.x.x.x:6379 (or use spring.redis.host/port)
 *
 * Without Redis, InMemoryRateLimiter is used (single-instance, no horizontal scaling).
 *
 * Falls back to in-memory bucket creation only if Redis is unreachable on first request,
 * so a Redis outage degrades gracefully instead of denying all traffic.
 */
@Component
@Profile("redis")
public class RedisRateLimiter implements RateLimiter {

    private static final Logger log = LoggerFactory.getLogger(RedisRateLimiter.class);

    @Value("${rate.limit.capacity:60}")
    private int capacity;

    @Value("${rate.limit.refill-minutes:1}")
    private int refillMinutes;

    @Value("${rate.limit.redis-uri:redis://localhost:6379}")
    private String redisUri;

    // R6.53 #3: real Redis-backed proxy manager (was: commented out + in-memory fallback)
    private LettuceBasedProxyManager<byte[]> proxyManager;
    private final InMemoryRateLimiter fallback = new InMemoryRateLimiter();
    private volatile boolean redisHealthy = false;

    @Override
    public boolean tryConsume(String key) {
        if (!redisHealthy) {
            // Lazy-init on first call so Redis is only contacted when needed
            try {
                initProxyManager();
                redisHealthy = true;
                log.info("RedisRateLimiter: connected to {} (proxy manager initialized)", redisUri);
            } catch (Exception e) {
                log.warn("RedisRateLimiter: failed to connect to {} — falling back to in-memory for this request. Reason: {}",
                        redisUri, e.getMessage());
                return fallback.tryConsume(key);
            }
        }
        try {
            byte[] keyBytes = key.getBytes();
            Bucket bucket = proxyManager.builder().build(keyBytes, () -> createBucketSpec());
            boolean allowed = bucket.tryConsume(1);
            return allowed;
        } catch (Exception e) {
            log.warn("RedisRateLimiter: Redis call failed ({}). Falling back to in-memory for this request.", e.getMessage());
            return fallback.tryConsume(key);
        }
    }

    @Override
    public int getCapacity() { return capacity; }

    @Override
    public long getRefillSeconds() { return Math.max(refillMinutes * 60L, 1); }

    private synchronized void initProxyManager() {
        if (proxyManager != null) return;
        RedisClient client = RedisClient.create(RedisURI.create(redisUri));
        StatefulRedisConnection<String, byte[]> connection = client.connect(
                io.lettuce.core.codec.ByteArrayCodec.INSTANCE);
        this.proxyManager = LettuceBasedProxyManager.builderFor(connection)
                .withExpirationStrategy(
                        io.github.bucket4j.redis.consts.LuaScripts.expireAfterAccess(
                                Duration.ofMinutes(refillMinutes * 5L)))
                .withRecoveryStrategy(RecoveryStrategy.RECONSTRUCT)
                .build();
    }

    private io.github.bucket4j.distributed.BucketProxy createBucketSpec() {
        Bandwidth limit = Bandwidth.classic(capacity,
                Refill.intervally(capacity, Duration.ofMinutes(refillMinutes)));
        return Bucket.builder().addLimit(limit).build();
    }

    /**
     * R6.53 #3: Configuration that wires the Lettuce client + connection as beans so
     * RedisRateLimiter can inject them in real deployments. Currently RedisRateLimiter
     * self-initializes lazily (above), but this config provides the conventional path
     * for test-time injection.
     */
    @Configuration
    @ConditionalOnClass(name = "io.lettuce.core.RedisClient")
    static class RedisClientConfig {
        @Bean(destroyMethod = "shutdown")
        public RedisClient redisClient(@Value("${rate.limit.redis-uri:redis://localhost:6379}") String uri) {
            return RedisClient.create(RedisURI.create(uri));
        }
    }
}
