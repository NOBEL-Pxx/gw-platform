package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Map;
import java.util.concurrent.ExecutorService;

import static org.junit.jupiter.api.Assertions.*;

/**
 * R6.83: parallel probes via CompletableFuture + ExecutorService.
 *
 * <p>Test goals:
 * <ol>
 *   <li>HealthController declares an ExecutorService field for probe fan-out</li>
 *   <li>Smoke gate: probeExecutor is initialized + active after @PostConstruct equivalent.
 *       (The strongest proof of parallelism is test #3 — wall-clock under artificial delay.)</li>
 *   <li>Wall-clock time for two slow probes is < sum of probe latencies —
 *       proves they actually ran concurrently</li>
 *   <li>Per-component failure isolation: ES failure does not affect Mongo status</li>
 *   <li>Response envelope keys unchanged at top level + components level</li>
 * </ol>
 *
 * <p>This test uses reflection (no Spring context) to keep it fast + deterministic.
 * Real Spring integration is covered by the zsmoke {@code api-health} check on zjlab.
 * zsmoke `api-health` check is unchanged for R6.83 — this is latency-only, no new
 * functional assertion. Future R6.84+ may add `api-health-parallel` zsmoke check
 * asserting max(latency_ms) < sum(latency_ms) for prod concurrency proof.
 *
 * <p>{@code @PostConstruct initProbeExecutor()} only fires inside Spring container,
 * so {@code @BeforeEach} setup manually calls it. {@code @PreDestroy} is invoked in
 * {@code @AfterEach} (N8: leaked 2 daemon threads per @Test without cleanup).
 */
class HealthControllerParallelTest {

    /** Probe delay per probe in milliseconds. 80ms × 2 probes = 160ms sequential, ~80ms parallel. */
    private static final long SLEEP_MS = 80L;
    /** Wall-clock upper bound = sum (160ms) minus 20ms headroom for thread startup. */
    private static final long WALL_THRESHOLD_MS = 140L;
    /** Wall-clock lower bound = max (80ms) minus 5ms headroom for thread scheduling jitter. */
    private static final long WALL_MIN_MS = 75L;

    private HealthController controller;

    @BeforeEach
    void setUp() throws Exception {
        controller = new HealthController();
        // @PostConstruct doesn't fire in plain JUnit; invoke manually so probeExecutor is initialized.
        Method init = HealthController.class.getDeclaredMethod("initProbeExecutor");
        init.setAccessible(true);
        init.invoke(controller);
    }

    @AfterEach
    void tearDown() throws Exception {
        // N8: shutdown executor to release daemon threads (otherwise 2 threads leak per @Test method).
        Method shutdown = HealthController.class.getDeclaredMethod("shutdownProbeExecutor");
        shutdown.setAccessible(true);
        shutdown.invoke(controller);
    }

    /** R6.83 #1: HealthController must declare an ExecutorService field. */
    @Test
    void declaresExecutorServiceField() throws Exception {
        Field[] fields = HealthController.class.getDeclaredFields();
        boolean hasExecutor = false;
        for (Field f : fields) {
            if (ExecutorService.class.isAssignableFrom(f.getType())) {
                hasExecutor = true;
                break;
            }
        }
        assertTrue(hasExecutor,
                "R6.83: HealthController must declare an ExecutorService field for probe fan-out");
    }

    /**
     * R6.83 #2: SMOKE GATE — probeExecutor is initialized and active after initProbeExecutor().
     *
     * <p>This is intentionally a weaker assertion than originally designed (originally: bytecode
     * introspection to find CompletableFuture.allOf invocation). Reasoning: the wall-clock test
     * (#3) is the strongest concurrency proof — if probes are sequential, wall ~160ms; if parallel,
     * wall ~80ms. The smoke gate here just verifies the executor field exists + is non-null + is
     * not shut down, which is necessary but not sufficient for parallelism. Real concurrency
     * proof lives in {@code parallelProbesRunConcurrently}.
     */
    @Test
    void probeExecutorIsInitializedAndActive() throws Exception {
        Field executorField = null;
        for (Field f : HealthController.class.getDeclaredFields()) {
            if (ExecutorService.class.isAssignableFrom(f.getType())) {
                executorField = f;
                break;
            }
        }
        assertNotNull(executorField, "R6.83: must have ExecutorService field");
        executorField.setAccessible(true);
        Object executor = executorField.get(controller);
        assertNotNull(executor, "R6.83: probeExecutor must be initialized (PostConstruct invoked)");
        assertFalse(((ExecutorService) executor).isShutdown(),
                "R6.83: probeExecutor must be active (not shutdown)");
    }

    /** R6.83 #3: parallel wall-clock < sum of probe latencies. */
    @Test
    void parallelProbesRunConcurrently() throws Exception {
        // Override probeElasticsearch and probeMongo via subclass to inject artificial delays.
        // This proves the executor actually runs them concurrently — if sequential, wall ~sum.
        HealthController slowController = new HealthController() {
            @Override
            boolean probeElasticsearch() {
                try { Thread.sleep(SLEEP_MS); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                return true;
            }
            @Override
            boolean probeMongo() {
                try { Thread.sleep(SLEEP_MS); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                return true;
            }
        };
        Method init = HealthController.class.getDeclaredMethod("initProbeExecutor");
        init.setAccessible(true);
        init.invoke(slowController);

        long t0 = System.currentTimeMillis();
        Response<Map<String, Object>> resp = slowController.health();
        long wall = System.currentTimeMillis() - t0;

        assertNotNull(resp);
        assertTrue(wall < WALL_THRESHOLD_MS,
                "R6.83: parallel probes must run concurrently — wall=" + wall + "ms but expected < " + WALL_THRESHOLD_MS + "ms (sum=" + (2 * SLEEP_MS) + "ms)");
        assertTrue(wall >= WALL_MIN_MS,
                "R6.83: probes must actually execute — wall=" + wall + "ms but expected >= " + WALL_MIN_MS + "ms");

        // Clean up the slowController's executor.
        Method shutdown = HealthController.class.getDeclaredMethod("shutdownProbeExecutor");
        shutdown.setAccessible(true);
        shutdown.invoke(slowController);
    }

    /**
     * R6.83 #4: ES failure does not affect Mongo status.
     * (Renamed from "esFailureDoesNotBlockMongoResult" — the original name conflated "block"
     * with "isolation". The correct property is isolation, not blocking. Blocking is verified
     * in #3 via wall-clock proof.)
     */
    @Test
    void esFailureDoesNotAffectMongoStatus() throws Exception {
        HealthController mixedController = new HealthController() {
            @Override
            boolean probeElasticsearch() {
                throw new RuntimeException("simulated ES failure");
            }
            @Override
            boolean probeMongo() {
                return true;
            }
        };
        Method init = HealthController.class.getDeclaredMethod("initProbeExecutor");
        init.setAccessible(true);
        init.invoke(mixedController);

        Response<Map<String, Object>> resp = mixedController.health();
        Map<String, Object> data = resp.getData();
        Map<?, ?> components = (Map<?, ?>) data.get("components");

        assertEquals("DOWN", ((Map<?, ?>) components.get("elasticsearch")).get("status"),
                "ES probe should report DOWN on exception");
        assertEquals("UP", ((Map<?, ?>) components.get("mongo")).get("status"),
                "R6.83: Mongo probe must NOT be affected by ES probe failure (per-component isolation)");

        Method shutdown = HealthController.class.getDeclaredMethod("shutdownProbeExecutor");
        shutdown.setAccessible(true);
        shutdown.invoke(mixedController);
    }

    /** R6.83 #5: top-level envelope keys unchanged + components keys unchanged. */
    @Test
    void responseEnvelopeKeysUnchanged() {
        Response<Map<String, Object>> resp = controller.health();
        assertEquals("0", resp.getError().getCode());

        Map<String, Object> data = resp.getData();
        // Top-level keys unchanged
        assertTrue(data.containsKey("status"));
        assertTrue(data.containsKey("version"));
        assertTrue(data.containsKey("timestamp"));
        assertTrue(data.containsKey("components"));

        // components sub-keys unchanged
        Map<?, ?> components = (Map<?, ?>) data.get("components");
        assertTrue(components.containsKey("app"));
        assertTrue(components.containsKey("elasticsearch"));
        assertTrue(components.containsKey("mongo"));
    }
}
