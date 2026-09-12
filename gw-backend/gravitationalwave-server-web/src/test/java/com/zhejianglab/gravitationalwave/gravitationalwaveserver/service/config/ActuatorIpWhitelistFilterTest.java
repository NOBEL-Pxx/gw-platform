package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.lang.reflect.Field;
import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.*;

/**
 * R6.95-C: unit tests for {@link ActuatorIpWhitelistFilter}.
 *
 * <p>Test goals:
 * <ol>
 *   <li>WHITELIST_PREFIXES covers loopback (127.x) + Docker bridge (172.16-172.31)
 *       + private (10.x) + host network (192.168.x) — comprehensive whitelist</li>
 *   <li>doFilterInternal returns HTTP 403 for non-whitelisted IPs on /actuator/**</li>
 *   <li>doFilterInternal allows whitelisted IPs on /actuator/** (chain.doFilter called)</li>
 *   <li>doFilterInternal passes through non-/actuator/** regardless of source IP</li>
 *   <li>WHITELIST_PREFIXES rejects public IPs (8.8.8.8, 1.1.1.1, 192.0.2.1) — no false negatives</li>
 *   <li>Defense in depth: filter covers ALL /actuator/** sub-paths (prometheus, health, info)</li>
 * </ol>
 *
 * <p>This test uses Spring's MockHttpServletRequest/Response (no Spring context needed).
 * Direct {@code new ActuatorIpWhitelistFilter()} instantiation — no @Autowired injection.
 * Reflection used to read the private {@code WHITELIST_PREFIXES} constant for comprehensive coverage.
 *
 * <p>The filter is deployed in R6.94-A to close a security gap where /actuator/** was exposed
 * to any container in {@code gw-net} (172.x Docker bridge). These tests pin the contract
 * so future modifications can't accidentally allow public IPs or block legitimate scrapers.
 */
class ActuatorIpWhitelistFilterTest {

    private ActuatorIpWhitelistFilter filter;

    @BeforeEach
    void setUp() {
        filter = new ActuatorIpWhitelistFilter();
    }

    /**
     * R6.95-C #1: WHITELIST_PREFIXES covers loopback + Docker bridge + private + host.
     * Uses reflection to read the private static constant.
     */
    @Test
    @DisplayName("R6.95-C: WHITELIST_PREFIXES covers loopback + Docker bridge 172.16-31 + 192.168 + 10.x")
    void whitelistCoversExpectedNetworks() throws Exception {
        Field field = ActuatorIpWhitelistFilter.class.getDeclaredField("WHITELIST_PREFIXES");
        field.setAccessible(true);
        String[] prefixes = (String[]) field.get(null);

        // Must include loopback
        assertTrue(Arrays.asList(prefixes).contains("127."),
            "R6.95-C: whitelist must include loopback prefix '127.' for docker exec access");
        // Must include Docker bridge range 172.16-172.31
        for (int second = 16; second <= 31; second++) {
            String prefix = "172." + second + ".";
            assertTrue(Arrays.asList(prefixes).contains(prefix),
                "R6.95-C: whitelist must include Docker bridge prefix '" + prefix + "'");
        }
        // Must include private + host
        assertTrue(Arrays.asList(prefixes).contains("10."),
            "R6.95-C: whitelist must include private prefix '10.'");
        assertTrue(Arrays.asList(prefixes).contains("192.168."),
            "R6.95-C: whitelist must include host prefix '192.168.'");
    }

    /**
     * R6.95-C #2: doFilterInternal returns HTTP 403 for non-whitelisted IPs on /actuator/**.
     * Example: 8.8.8.8 (Google DNS) attempting /actuator/prometheus.
     */
    @Test
    @DisplayName("R6.95-C: blocks /actuator/** from public IP (8.8.8.8) with HTTP 403")
    void blocksActuatorFromPublicIp() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/actuator/prometheus");
        req.setRemoteAddr("8.8.8.8");
        MockHttpServletResponse resp = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(req, resp, chain);

        assertEquals(403, resp.getStatus(),
            "R6.95-C: non-whitelisted IP must get HTTP 403 on /actuator/**");
        assertNull(chain.getRequest(),
            "R6.95-C: chain.doFilter MUST NOT be called for blocked requests");
    }

    /**
     * R6.95-C #3: doFilterInternal allows whitelisted IPs on /actuator/**.
     * Example: 172.18.0.5 (gw-prometheus scraper in Docker bridge) accessing /actuator/prometheus.
     */
    @Test
    @DisplayName("R6.95-C: allows /actuator/** from whitelisted Docker bridge IP (172.18.0.5)")
    void allowsActuatorFromDockerBridge() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/actuator/prometheus");
        req.setRemoteAddr("172.18.0.5");
        MockHttpServletResponse resp = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(req, resp, chain);

        assertEquals(200, resp.getStatus(),
            "R6.95-C: whitelisted Docker bridge IP must get HTTP 200 on /actuator/**");
        assertNotNull(chain.getRequest(),
            "R6.95-C: chain.doFilter MUST be called for allowed requests");
    }

    /**
     * R6.95-C #4: doFilterInternal passes through non-/actuator/** regardless of source IP.
     * Example: public IP 1.1.1.1 accessing /api/health (public API path) must NOT be blocked.
     */
    @Test
    @DisplayName("R6.95-C: passes through /api/health regardless of source IP")
    void passesThroughNonActuatorPaths() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/api/health");
        req.setRemoteAddr("1.1.1.1");  // public IP
        MockHttpServletResponse resp = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(req, resp, chain);

        assertNotNull(chain.getRequest(),
            "R6.95-C: non-/actuator/** must pass through regardless of source IP");
        assertEquals(200, resp.getStatus(),
            "R6.95-C: filter must NOT mutate response status for non-/actuator/** paths");
    }

    /**
     * R6.95-C #5: WHITELIST_PREFIXES (via doFilterInternal) rejects /actuator/info from public IP.
     * /actuator/info exposes app version/name/R-numbering — info disclosure (R6.95 pre-existing issue #5).
     */
    @Test
    @DisplayName("R6.95-C: blocks /actuator/info from public IP — info disclosure defense")
    void blocksActuatorInfoFromPublicIp() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/actuator/info");
        req.setRemoteAddr("192.0.2.1");  // TEST-NET-1 documentation range
        MockHttpServletResponse resp = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(req, resp, chain);

        assertEquals(403, resp.getStatus(),
            "R6.95-C: /actuator/info must be blocked from public IPs (info disclosure defense)");
    }

    /**
     * R6.95-C #6: WHITELIST_PREFIXES accepts loopback 127.0.0.1 (docker exec into gw-backend).
     */
    @Test
    @DisplayName("R6.95-C: allows loopback 127.0.0.1 on /actuator/** for docker exec")
    void allowsLoopbackForDockerExec() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/actuator/health");
        req.setRemoteAddr("127.0.0.1");
        MockHttpServletResponse resp = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(req, resp, chain);

        assertEquals(200, resp.getStatus(),
            "R6.95-C: loopback 127.0.0.1 must be whitelisted (docker exec use case)");
        assertNotNull(chain.getRequest());
    }

    /**
     * R6.95-C #7: WHITELIST_PREFIXES rejects /actuator/metrics from public IP too (full coverage).
     */
    @Test
    @DisplayName("R6.95-C: blocks /actuator/metrics from public IP — full coverage")
    void blocksActuatorMetricsFromPublicIp() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/actuator/metrics");
        req.setRemoteAddr("203.0.113.42");  // TEST-NET-3 documentation range
        MockHttpServletResponse resp = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(req, resp, chain);

        assertEquals(403, resp.getStatus(),
            "R6.95-C: /actuator/metrics must be blocked from public IPs");
    }

    /**
     * R6.95-C.2: null remoteAddr must be rejected on /actuator/** (defensive).
     * Filter source: {@code isWhitelisted(null)} returns {@code false}.
     */
    @Test
    @DisplayName("R6.95-C: blocks /actuator/** when remoteAddr is null (defensive)")
    void blocksActuatorWhenRemoteAddrIsNull() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/actuator/health");
        req.setRemoteAddr(null);
        MockHttpServletResponse resp = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(req, resp, chain);

        assertEquals(403, resp.getStatus(),
            "R6.95-C: null remoteAddr must be rejected on /actuator/** (defensive)");
        assertNull(chain.getRequest());
    }

    /**
     * R6.95-C.3 (boundary): 172.15.0.1 is just BELOW the Docker bridge range (172.16-172.31).
     * Must be blocked (not in 172.16.0.0/12).
     */
    @Test
    @DisplayName("R6.95-C: blocks 172.15.0.1 (just below Docker bridge range 172.16-31)")
    void blocksJustBelowDockerBridge() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/actuator/health");
        req.setRemoteAddr("172.15.0.1");
        MockHttpServletResponse resp = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(req, resp, chain);

        assertEquals(403, resp.getStatus(),
            "R6.95-C: 172.15.0.1 must be blocked (below 172.16/12 boundary)");
    }

    /**
     * R6.95-C.3 (boundary): 172.32.0.1 is just ABOVE the Docker bridge range (172.16-172.31).
     * Must be blocked.
     */
    @Test
    @DisplayName("R6.95-C: blocks 172.32.0.1 (just above Docker bridge range 172.16-31)")
    void blocksJustAboveDockerBridge() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/actuator/health");
        req.setRemoteAddr("172.32.0.1");
        MockHttpServletResponse resp = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(req, resp, chain);

        assertEquals(403, resp.getStatus(),
            "R6.95-C: 172.32.0.1 must be blocked (above 172.16/12 boundary)");
    }
}
