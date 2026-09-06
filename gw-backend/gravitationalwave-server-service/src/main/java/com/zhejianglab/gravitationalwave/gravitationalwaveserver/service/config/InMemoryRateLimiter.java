package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import io.github.bucket4j.Refill;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/**
 * Default single-instance rate limiter backed by ConcurrentHashMap.
 * R6.66.1: Removed @Profile("!redis") — RedisRateLimiter was deleted (was dead code that
 * never built successfully). Now this is the only RateLimiter implementation.
 */
@Component
public class InMemoryRateLimiter implements RateLimiter {

    private static final Logger log = LoggerFactory.getLogger(InMemoryRateLimiter.class);

    private final ConcurrentHashMap<String, Bucket> buckets = new ConcurrentHashMap<>();

    @Value("${rate.limit.capacity:60}")
    private int capacity = 60;

    @Value("${rate.limit.refill-minutes:1}")
    private int refillMinutes = 1;

    @Value("${rate.limit.cleanup-minutes:15}")
    private int cleanupMinutes = 15;

    @Override
    public boolean tryConsume(String key) {
        Bucket bucket = buckets.computeIfAbsent(key, k -> createNewBucket());
        return bucket.tryConsume(1);
    }

    @Override
    public int getCapacity() { return capacity; }

    @Override
    public long getRefillSeconds() { return Math.max(refillMinutes * 60L, 1); }

    private Bucket createNewBucket() {
        Bandwidth limit = Bandwidth.classic(capacity,
                Refill.intervally(capacity, Duration.ofMinutes(refillMinutes)));
        return Bucket.builder().addLimit(limit).build();
    }

    @Scheduled(fixedDelayString = "${rate.limit.cleanup-minutes:15}",
               initialDelayString = "${rate.limit.cleanup-minutes:15}",
               timeUnit = TimeUnit.MINUTES)
    public void cleanUpStaleBuckets() {
        int before = buckets.size();
        buckets.entrySet().removeIf(e -> e.getValue().getAvailableTokens() >= capacity);
        int removed = before - buckets.size();
        if (removed > 0) {
            log.info("Rate-limit bucket cleanup: removed {} stale entries ({} remaining)",
                    removed, buckets.size());
        }
    }
}
