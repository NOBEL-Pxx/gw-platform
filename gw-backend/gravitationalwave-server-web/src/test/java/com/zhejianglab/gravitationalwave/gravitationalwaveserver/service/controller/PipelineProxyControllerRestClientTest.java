package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * R6.98-C (PipelineProxyController migration): tests verifying
 * PipelineProxyController uses the shared {@link RestClient} bean (not
 * a local {@code RestTemplate}), and enforces the R6.98-C streaming OOM
 * guard (response body cap at 1 MiB).
 *
 * <p>Iron rules:
 * <ul>
 *   <li><b>R6.98-A</b>: all outbound HTTP MUST use the shared
 *       {@code CloseableHttpClient} bean via {@link RestClient}.</li>
 *   <li><b>R6.98-C</b>: streaming OOM guard — if upstream returns a
 *       response body larger than 1 MiB, the proxy MUST abort with HTTP 413
 *       (Payload Too Large) and log a warn. Prevents an attacker (or a
 *       buggy pipeline worker) from filling the JVM heap via a single
 *       proxy request.</li>
 * </ul>
 *
 * <p>Approach: same Spring {@link MockRestServiceServer} pattern as
 * {@code AuditServiceRestClientTest} -- validates wire-level format
 * without spinning up a real HTTP server.
 */
class PipelineProxyControllerRestClientTest {

    /**
     * R6.98-C streaming cap. Mirrors the R6.96-O6 cap for download endpoints;
     * applied here to the proxy because the same DoS surface (multi-GB FITS/ZIP)
     * is reachable through any /pipeline/... endpoint.
     */
    private static final int STREAMING_CAP_BYTES = 1024 * 1024; // 1 MiB

    private static final String UPSTREAM = "http://gw-pipeline:8200";

    private RestClient restClient;
    private MockRestServiceServer mockServer;
    private PipelineProxyController controller;

    @BeforeEach
    void setUp() throws Exception {
        RestClient.Builder builder = RestClient.builder();
        mockServer = MockRestServiceServer.bindTo(builder).build();
        restClient = builder.build();

        // R6.98-C: constructor injection of RestClient.
        controller = new PipelineProxyController(restClient);

        // Mirror the @PostConstruct initialization that Spring would perform
        // (allowedUpstreamHosts load from env). In unit tests we have no
        // Spring context, so invoke the @PostConstruct method directly.
        java.lang.reflect.Method m = PipelineProxyController.class
                .getDeclaredMethod("loadAllowedUpstreamHosts");
        m.setAccessible(true);
        m.invoke(controller);
    }

    @Test
    @DisplayName("R6.98-C #1: RestTemplate field removed (R6.98-A iron rule)")
    void restTemplateFieldRemoved() {
        boolean hasRestTemplate = false;
        for (Field f : PipelineProxyController.class.getDeclaredFields()) {
            if (f.getType().getSimpleName().equals("RestTemplate")) {
                hasRestTemplate = true;
                break;
            }
        }
        assertFalse(hasRestTemplate,
                "R6.98-A: PipelineProxyController must not declare a RestTemplate field; "
                + "use shared RestClient bean via constructor injection");
    }

    @Test
    @DisplayName("R6.98-C #2: GET /pipeline/audit/foo -> forwards as GET to upstream")
    void getForwardsToUpstream() throws Exception {
        mockServer.expect(requestTo(UPSTREAM + "/pipeline/audit/foo"))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess("ok-response".getBytes(), MediaType.APPLICATION_JSON));

        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/pipeline/audit/foo");
        req.setRemoteAddr("gw-frontend");

        var resp = controller.proxyGet(req);
        assertEquals(200, resp.getStatusCode().value());
        assertArrayEquals("ok-response".getBytes(), resp.getBody());
        mockServer.verify();
    }

    @Test
    @DisplayName("R6.98-C #3: POST /pipeline/batch/submit -> forwards body + POST method")
    void postForwardsBody() throws Exception {
        mockServer.expect(requestTo(UPSTREAM + "/pipeline/batch/submit"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess("{\"job_id\":\"j-1\"}".getBytes(), MediaType.APPLICATION_JSON));

        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/pipeline/batch/submit");
        req.setRemoteAddr("127.0.0.1");
        req.setContent("{\"op\":\"start\"}".getBytes());
        req.setContentType(MediaType.APPLICATION_JSON_VALUE);

        var resp = controller.proxyPost(req);
        assertEquals(200, resp.getStatusCode().value());
        assertNotNull(resp.getBody());
        mockServer.verify();
    }

    @Test
    @DisplayName("R6.98-C #4: streaming cap > 1 MiB returns 413 Payload Too Large")
    void streamingCapEnforced() throws Exception {
        // Build a response body just over the cap (1 MiB + 1 byte).
        byte[] huge = new byte[STREAMING_CAP_BYTES + 1];
        Arrays.fill(huge, (byte) 'A');

        mockServer.expect(requestTo(UPSTREAM + "/pipeline/hips-tile-resolve"))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess(huge, MediaType.APPLICATION_OCTET_STREAM));

        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/pipeline/hips-tile-resolve");
        req.setRemoteAddr("gw-frontend");

        var resp = controller.proxyGet(req);
        assertEquals(413, resp.getStatusCode().value(),
                "R6.98-C: response > 1 MiB must return 413; got: " + resp.getStatusCode());
        assertNotNull(resp.getBody());
        // Body is an error message, not the streamed payload.
        String bodyStr = new String(resp.getBody());
        assertTrue(bodyStr.contains("R6.98-C") || bodyStr.contains("too large")
                        || bodyStr.contains("payload"),
                "R6.98-C: error body must mention streaming cap; got: " + bodyStr);
        mockServer.verify();
    }

    @Test
    @DisplayName("R6.98-C #5: response exactly at 1 MiB cap is allowed (boundary)")
    void responseAtCapIsAllowed() throws Exception {
        byte[] atCap = new byte[STREAMING_CAP_BYTES];
        Arrays.fill(atCap, (byte) 'B');

        mockServer.expect(requestTo(UPSTREAM + "/pipeline/somewhere"))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess(atCap, MediaType.APPLICATION_OCTET_STREAM));

        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/pipeline/somewhere");
        req.setRemoteAddr("gw-frontend");

        var resp = controller.proxyGet(req);
        assertEquals(200, resp.getStatusCode().value(),
                "R6.98-C: response exactly at cap must be allowed; got: " + resp.getStatusCode());
        assertEquals(STREAMING_CAP_BYTES, resp.getBody().length,
                "R6.98-C: response body length must equal cap");
        mockServer.verify();
    }

    @Test
    @DisplayName("R6.98-C #6: IP whitelist still enforced (R6.73 #2)")
    void ipWhitelistStillEnforced() throws Exception {
        mockServer.expect(requestTo(UPSTREAM + "/pipeline/audit"))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess("ok".getBytes(), MediaType.APPLICATION_JSON));

        // Remote from outside the default whitelist (gw-frontend, 127.0.0.1, ::1, localhost).
        // The controller checks getRemoteHost(); MockHttpServletRequest defaults
        // getRemoteHost() to "localhost" regardless of setRemoteAddr(), so we
        // must explicitly setRemoteHost() to simulate a non-whitelisted caller.
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/pipeline/audit");
        req.setRemoteAddr("10.99.99.99");
        req.setRemoteHost("10.99.99.99");

        var resp = controller.proxyGet(req);
        assertEquals(403, resp.getStatusCode().value(),
                "R6.73 #2: non-whitelisted remote must 403; got: " + resp.getStatusCode());
        // No mock server verify() — no upstream call should have been made.
    }

    @Test
    @DisplayName("R6.98-C #7: DELETE method routes through same forward()")
    void deleteMethodForwarded() throws Exception {
        mockServer.expect(requestTo(UPSTREAM + "/pipeline/cancel"))
                .andExpect(method(HttpMethod.DELETE))
                .andRespond(withSuccess());

        MockHttpServletRequest req = new MockHttpServletRequest("DELETE", "/pipeline/cancel");
        req.setRemoteAddr("gw-frontend");

        var resp = controller.proxyDelete(req);
        assertEquals(200, resp.getStatusCode().value());
        mockServer.verify();
    }
}
