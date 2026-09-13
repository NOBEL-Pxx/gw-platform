package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.audit;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.lang.reflect.Field;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withException;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.http.HttpMethod.POST;

/**
 * R6.98-B (AuditService migration): tests verifying AuditService uses the
 * shared {@link RestClient} bean (not a local {@code RestTemplate}).
 *
 * <p>Iron rule R6.98-A: all outbound HTTP MUST use the shared
 * {@code CloseableHttpClient} bean via {@link RestClient}. No ad-hoc
 * {@code new RestTemplate()} inside service methods.
 *
 * <p>Approach: use Spring's {@link MockRestServiceServer} bound to the same
 * {@link RestClient.Builder} configuration as {@code HttpClientConfig.sharedRestClient()}.
 * This validates the wire-level request format (URL, method, headers, body)
 * without spinning up a real HTTP server.
 *
 * <p>Fail-closed semantics (token empty) and fire-and-forget counter behavior
 * are also verified here so a future refactor cannot silently break them.
 */
class AuditServiceRestClientTest {

    private static final String AUDIT_URL = "http://gw-pipeline:8200/pipeline/audit/ingest";
    private static final String AUDIT_TOKEN = "test-token-abc-123";

    private RestClient restClient;
    private MockRestServiceServer mockServer;
    private AuditService auditService;

    @BeforeEach
    void setUp() throws Exception {
        RestClient.Builder builder = RestClient.builder();
        mockServer = MockRestServiceServer.bindTo(builder).build();
        restClient = builder.build();

        // R6.98-B: AuditService now requires a RestClient via constructor injection.
        auditService = new AuditService(restClient);

        Field fUrl = AuditService.class.getDeclaredField("auditUrl");
        fUrl.setAccessible(true);
        fUrl.set(auditService, AUDIT_URL);

        Field fToken = AuditService.class.getDeclaredField("auditToken");
        fToken.setAccessible(true);
        fToken.set(auditService, AUDIT_TOKEN);

        Field fTimeout = AuditService.class.getDeclaredField("timeoutMs");
        fTimeout.setAccessible(true);
        fTimeout.set(auditService, 3000);
    }

    @Test
    @DisplayName("R6.98-B #1: AuditService POSTs to audit URL via RestClient (not RestTemplate)")
    void postsViaRestClient() throws Exception {
        mockServer.expect(requestTo(AUDIT_URL))
                .andExpect(method(POST))
                .andExpect(header("X-Audit-Token", AUDIT_TOKEN))
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andRespond(withSuccess());

        auditService.recordHttpCall("GET", "/api/test", "127.0.0.1", "ua", 200, 42L, Instant.now());

        mockServer.verify();
        assertEquals(1L, readCounter("sentOk"),
                "successful POST must increment sentOk; got: " + readCounter("sentOk"));
    }

    @Test
    @DisplayName("R6.98-B #2: AuditService POSTs JSON body with expected fields")
    void postsJsonBody() throws Exception {
        mockServer.expect(requestTo(AUDIT_URL))
                .andExpect(method(POST))
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"source\":\"backend\"")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"method\":\"GET\"")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"request_path\":\"/api/x\"")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"status_code\":200")))
                .andRespond(withSuccess());

        auditService.recordHttpCall("GET", "/api/x", "10.0.0.1", null, 200, 100L, Instant.now());

        mockServer.verify();
    }

    @Test
    @DisplayName("R6.98-B #3: fail-closed when auditToken empty (no POST sent, droppedDisabled++)")
    void failClosedWhenTokenEmpty() throws Exception {
        Field fToken = AuditService.class.getDeclaredField("auditToken");
        fToken.setAccessible(true);
        fToken.set(auditService, "");

        auditService.recordHttpCall("GET", "/api/x", "127.0.0.1", null, 200, 1L, Instant.now());

        assertEquals(1L, readCounter("droppedDisabled"),
                "empty token must increment droppedDisabled; got: " + readCounter("droppedDisabled"));
        assertEquals(0L, readCounter("sentOk"),
                "empty token must NOT increment sentOk; got: " + readCounter("sentOk"));
    }

    @Test
    @DisplayName("R6.98-B #4: HTTP 4xx -> droppedFailed++ (NOT sentOk)")
    void http4xxIncrementsDroppedFailed() throws Exception {
        mockServer.expect(requestTo(AUDIT_URL))
                .andExpect(method(POST))
                .andRespond(withStatus(org.springframework.http.HttpStatus.BAD_REQUEST));

        auditService.recordHttpCall("POST", "/api/x", "127.0.0.1", null, 500, 10L, Instant.now());

        assertEquals(1L, readCounter("droppedFailed"),
                "4xx response must increment droppedFailed; got: " + readCounter("droppedFailed"));
        assertEquals(0L, readCounter("sentOk"),
                "4xx response must NOT increment sentOk; got: " + readCounter("sentOk"));
    }

    @Test
    @DisplayName("R6.98-B #5: IOException (network down) -> droppedFailed++")
    void ioExceptionIncrementsDroppedFailed() throws Exception {
        // MockRestResponseCreators.withException(IOException) simulates a transport-level
        // failure. The AuditService catch-all Exception handler must count it as dropped.
        mockServer.expect(requestTo(AUDIT_URL))
                .andExpect(method(POST))
                .andRespond(withException(new java.net.SocketException("connection refused")));

        auditService.recordHttpCall("GET", "/api/x", "127.0.0.1", null, 500, 5L, Instant.now());

        assertEquals(1L, readCounter("droppedFailed"),
                "transport IOException must increment droppedFailed; got: " + readCounter("droppedFailed"));
    }

    @Test
    @DisplayName("R6.98-B #6: counters() returns all three keys")
    void countersReturnsAllKeys() {
        Map<String, Long> c = auditService.counters();
        assertNotNull(c, "counters() must return a map");
        assertTrue(c.containsKey("sent_ok"), "counters() must contain sent_ok");
        assertTrue(c.containsKey("dropped_disabled"), "counters() must contain dropped_disabled");
        assertTrue(c.containsKey("dropped_failed"), "counters() must contain dropped_failed");
    }

    @Test
    @DisplayName("R6.98-B #7: RestTemplate field removed (R6.98-A shared-client iron rule)")
    void restTemplateFieldRemoved() {
        boolean hasRestTemplate = false;
        for (Field f : AuditService.class.getDeclaredFields()) {
            if (f.getType().getSimpleName().equals("RestTemplate")) {
                hasRestTemplate = true;
                break;
            }
        }
        assertFalse(hasRestTemplate,
                "R6.98-A: AuditService must not declare a RestTemplate field; "
                + "use shared RestClient bean via constructor injection");
    }

    private long readCounter(String name) throws Exception {
        Field f = AuditService.class.getDeclaredField(name);
        f.setAccessible(true);
        return ((AtomicLong) f.get(auditService)).get();
    }
}
