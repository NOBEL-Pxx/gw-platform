package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.BucketConfiguration;
import io.github.bucket4j.Refill;
import io.github.bucket4j.distributed.BucketProxy;
import io.github.bucket4j.distributed.ExpirationAfterWriteStrategy;
import io.github.bucket4j.distributed.proxy.ProxyManager;
import io.github.bucket4j.redis.lettuce.cas.LettuceBasedProxyManager;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.codec.ByteArrayCodec;
import io.lettuce.core.codec.RedisCodec;
import io.lettuce.core.codec.StringCodec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.time.Duration;

/**
 * R6.89: Distributed multi-instance rate limiter via bucket4j + Lettuce + Redis.
 *
 * <p>Active when Spring profile "redis" is set. Uses bucket4j's Lettuce-based proxy manager
 * which performs atomic CAS via Redis Lua scripts — safe for concurrent access across N
 * backend instances sharing the same Redis service.
 *
 * <p>Prerequisites (env / config):
 * <ul>
 *   <li>{@code bucket4j-redis} + {@code lettuce-core} on the classpath (declared in root pom.xml + service pom.xml)</li>
 *   <li>{@code application-redis.properties} on the active profile (Spring Data Redis + RATE_LIMIT_REDIS_URI)</li>
 *   <li>A reachable Redis service (env: REDIS_HOST, REDIS_PORT, optional REDIS_PASSWORD)</li>
 * </ul>
 *
 * <p>Failure mode: if Redis is unreachable, {@link #tryConsume(String)} catches the exception,
 * logs an error, and returns {@code true} (fail-open). This is the same behavior as the
 * in-memory impl degrades to on JVM crash — better to allow legitimate traffic through than
 * to 5xx-storm the user. Trade-off documented in r689-summary.
 *
 * <p>Re-introduced in R6.89 after R6.66.1 deleted it as dead code; the property scaffold
 * in application-redis.properties was preserved through R6.66.1..R6.88, so adding back the
 * implementation is non-breaking (the @Profile guard means dev/local keeps using
 * InMemoryRateLimiter unchanged).
 */
@Component
@Profile("redis")
public class RedisRateLimiter implements RateLimiter {

    private static final Logger log = LoggerFactory.getLogger(RedisRateLimiter.class);

    @Value("${rate.limit.capacity:60}")
    private int capacity = 60;

    @Value("${rate.limit.refill-minutes:1}")
    private int refillMinutes = 1;

    @Value("${rate.limit.redis-uri:redis://localhost:6379}")
    private String redisUri;

    @Value("${rate.limit.cleanup-minutes:15}")
    private long cleanupMinutes = 15;

    private RedisClient redisClient;
    /**
     * R6.89: bucket4j 8.10.x Lettuce proxy manager expects a {@code StatefulRedisConnection<String, byte[]>}
     * so bucket keys are strings but bucket values are raw byte arrays. We use Lettuce's
     * {@link io.lettuce.core.codec.RedisCodec} to override the default String/String codec.
     */
    private StatefulRedisConnection<String, byte[]> connection;
    private ProxyManager<String> proxyManager;

    /**
     * R6.85-A-V1MARKER: emit a recognizable startup log line so {@code build-and-deploy-jar.py}'s
     * {@code check_marker_log} AND-check can confirm the bean lifecycle completed.
     */
    @PostConstruct
    public void init() {
        log.info("R6.89: RedisRateLimiter initializing (uri={}, capacity={}, refill={}min)",
                redisUri, capacity, refillMinutes);
        try {
            this.redisClient = RedisClient.create(RedisURI.create(redisUri));
            // R6.89: override Lettuce's default String/String codec to <String, byte[]> so the
            // bucket4j-redis Lettuce proxy manager (which expects byte[] values for raw bucket
            // state serialization) accepts the connection. The key codec stays String (the bucket
            // keys are request keys like "ip:1.2.3.4"); the value codec becomes ByteArrayCodec
            // so bucket4j can store its internal byte-serialized state directly.
            RedisCodec<String, byte[]> codec = RedisCodec.of(StringCodec.UTF8, ByteArrayCodec.INSTANCE);
            this.connection = redisClient.connect(codec);
            this.proxyManager = LettuceBasedProxyManager.builderFor(connection)
                    .withExpirationStrategy(ExpirationAfterWriteStrategy.fixedTimeToLive(Duration.ofMinutes(cleanupMinutes)))
                    .build();
            log.info("R6.89: RedisRateLimiter initialized (proxy manager ready)");
        } catch (Exception e) {
            // Don't fail boot — fall back to fail-open behavior in tryConsume().
            log.error("R6.89: RedisRateLimiter init failed (will fail-open in tryConsume): {}", e.getMessage(), e);
        }
    }

    /**
     * R6.85-A-PREDESTROY: log shutdown and release the Lettuce connection.
     */
    @PreDestroy
    public void shutdown() {
        log.info("R6.89: RedisRateLimiter shutting down");
        try {
            if (connection != null) connection.close();
            if (redisClient != null) redisClient.shutdown();
        } catch (Exception e) {
            log.warn("R6.89: RedisRateLimiter shutdown error (non-fatal): {}", e.getMessage());
        }
    }

    @Override
    public boolean tryConsume(String key) {
        if (proxyManager == null) {
            // Init failed (Redis unreachable at boot). Fail-open with a metric log line.
            log.error("RedisRateLimiter proxy manager unavailable — failing open for key={}", key);
            return true;
        }
        try {
            BucketConfiguration config = BucketConfiguration.builder()
                    .addLimit(Bandwidth.classic(capacity,
                            Refill.intervally(capacity, Duration.ofMinutes(refillMinutes))))
                    .build();
            BucketProxy bucket = proxyManager.builder().build(key, () -> config);
            return bucket.tryConsume(1);
        } catch (Exception e) {
            // Fail-open: don't 5xx-storm if Redis hiccups mid-flight.
            log.error("RedisRateLimiter tryConsume failed (failing open) for key={}: {}", key, e.getMessage());
            return true;
        }
    }

    @Override
    public int getCapacity() { return capacity; }

    @Override
    public long getRefillSeconds() { return Math.max(refillMinutes * 60L, 1); }
}