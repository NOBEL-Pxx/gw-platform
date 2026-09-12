package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.interceptor.AsyncUncaughtExceptionHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.AsyncConfigurer;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * R6.90 B1: AsyncConfig for the ImageCutoutController async-download refactor.
 *
 * <p>Replaces the synchronous {@code dataSet.download()} call in the controller
 * (which held the Tomcat request thread for the duration of the upstream
 * HTTP + file write). With this executor wired to {@code @Async("imageCutoutExecutor")}
 * on a service method, the controller returns immediately and the actual download
 * runs on a bounded background pool.
 *
 * <h3>Design notes</h3>
 * <ul>
 *   <li>2 core / 4 max threads: image cutout is a long-tail operation (upstream
 *       china-vo.org + file write to /app/Ali_PW). 2 concurrent requests absorb
 *       a 2x burst without unbounded queue growth; queueCapacity=50 bounds
 *       memory if every worker is stuck.</li>
 *   <li>{@code daemon=true}: mirrors the HealthController probe-executor pattern
 *       (R6.83) — daemon threads don't block JVM shutdown. Critical so a stuck
 *       cutout request cannot prevent graceful container exit.</li>
 *   <li>{@code threadNamePrefix="image-cutout-" + AtomicInteger}: forensic
 *       clarity in thread dumps (same NIT as HealthController).</li>
 *   <li>{@code setWaitForTasksToCompleteOnShutdown(true)} + 30s timeout: lets
 *       in-flight downloads finish (write to disk) instead of dropping partial
 *       files on the user. 30s is generous — single file writes should complete
 *       in <5s; the buffer absorbs GC pauses + slow disk.</li>
 *   <li>{@link AsyncUncaughtExceptionHandler}: logs uncaught @Async exceptions
 *       (the controller returns CompletableFuture so the caller sees failures,
 *       but internal pre-handler failures get logged for ops).</li>
 * </ul>
 *
 * <p>Iron rule R6.90-A: every @Async in this codebase MUST use a named executor
 * bean (not {@code SimpleAsyncTaskExecutor} which creates unbounded threads).
 */
@Configuration
@EnableAsync
public class AsyncConfig implements AsyncConfigurer {

    private static final Logger log = LoggerFactory.getLogger(AsyncConfig.class);

    @Bean(name = "imageCutoutExecutor")
    public Executor imageCutoutExecutor() {
        AtomicInteger seq = new AtomicInteger(0);
        ThreadFactory tf = r -> {
            Thread t = new Thread(r, "image-cutout-" + seq.incrementAndGet());
            t.setDaemon(true);
            return t;
        };
        ThreadPoolTaskExecutor exec = new ThreadPoolTaskExecutor();
        exec.setCorePoolSize(2);
        exec.setMaxPoolSize(4);
        exec.setQueueCapacity(50);
        exec.setThreadFactory(tf);
        exec.setThreadNamePrefix("image-cutout-");
        exec.setWaitForTasksToCompleteOnShutdown(true);
        exec.setAwaitTerminationSeconds(30);
        exec.initialize();
        return exec;
    }

    @Override
    public AsyncUncaughtExceptionHandler getAsyncUncaughtExceptionHandler() {
        return (ex, method, params) ->
            log.error("Uncaught exception in @Async method {}: {}",
                method.getName(), ex.getMessage(), ex);
    }
}
