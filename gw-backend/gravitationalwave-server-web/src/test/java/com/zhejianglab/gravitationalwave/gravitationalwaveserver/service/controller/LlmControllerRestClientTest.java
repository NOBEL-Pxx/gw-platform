package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
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
 * R6.98-D (LlmController migration): tests verifying LlmController uses the
 * dedicated TLS-pinned {@link RestClient} bean (NOT a local {@code RestTemplate}
 * and NOT the shared bean — TLS pinning for api.deepseek.com requires isolation).
 *
 * <p>Iron rules:
 * <ul>
 *   <li><b>R6.98-A</b>: all outbound HTTP MUST use a Spring-managed {@link RestClient}
 *       bean — no ad-hoc {@code new RestTemplate()}. The LLM controller uses a
 *       DEDICATED {@code llmRestClient} bean (not {@code sharedRestClient}) because
 *       TLS pinning for api.deepseek.com must not bleed into other consumers.</li>
 *   <li><b>R6.98-B</b> (response variant): outbound response MUST have
 *       {@code Content-Type: application/json}. HTML error pages from a CDN or
 *       misconfigured proxy MUST be rejected.</li>
 *   <li><b>R6.98-D</b>: dedicated {@code llmRestClient} bean is wired with a
 *       {@code CloseableHttpClient} whose {@code SSLContext} enforces SPKI
 *       SHA-256 pinning for api.deepseek.com.</li>
 * </ul>
 */
class LlmControllerRestClientTest {

    private static final String API_URL = "https://api.deepseek.com/v1/chat/completions";
    private static final String API_KEY = "sk-test-fake-key-abc123456789";

    private static final String DEEPSEEK_OK_BODY =
            "{\"id\":\"chatcmpl-abc\",\"object\":\"chat.completion\","
            + "\"created\":1700000000,\"model\":\"deepseek-chat\","
            + "\"choices\":[{\"index\":0,\"message\":"
            + "{\"role\":\"assistant\",\"content\":\"M31 is a spiral galaxy.\"},"
            + "\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":10,\"completion_tokens\":8}}";

    private RestClient restClient;
    private MockRestServiceServer mockServer;
    private LlmController controller;

    @BeforeEach
    void setUp() throws Exception {
        RestClient.Builder builder = RestClient.builder();
        mockServer = MockRestServiceServer.bindTo(builder).build();
        restClient = builder.build();

        controller = new LlmController(restClient);

        setField("apiKey", API_KEY);
        setField("apiUrl", API_URL);
        setField("model", "deepseek-chat");
        setField("dailyQuota", 500);
        setField("cacheTtlMinutes", 30);

        Method init = LlmController.class.getDeclaredMethod("init");
        init.setAccessible(true);
        init.invoke(controller);
    }

    @Test
    @DisplayName("R6.98-D #1: RestTemplate field removed (R6.98-A iron rule)")
    void restTemplateFieldRemoved() {
        boolean hasRestTemplate = false;
        for (Field f : LlmController.class.getDeclaredFields()) {
            if (f.getType().getSimpleName().equals("RestTemplate")) {
                hasRestTemplate = true;
                break;
            }
        }
        assertFalse(hasRestTemplate,
                "R6.98-A: LlmController must not declare a RestTemplate field; "
                + "use the dedicated llmRestClient bean via constructor injection");
    }

    @Test
    @DisplayName("R6.98-D #2: LlmController declares a final RestClient field (R6.98-A wiring)")
    void constructorInjectsRestClient() throws Exception {
        boolean hasRestClientField = false;
        for (Field f : LlmController.class.getDeclaredFields()) {
            if (f.getType().getSimpleName().equals("RestClient")) {
                hasRestClientField = true;
                assertTrue(java.lang.reflect.Modifier.isFinal(f.getModifiers()),
                        "R6.98-A: RestClient field must be final (constructor injection)");
                break;
            }
        }
        assertTrue(hasRestClientField,
                "R6.98-A: LlmController must declare a RestClient field for injection");
    }

    @Test
    @DisplayName("R6.98-D #3: POST /chat forwards to DeepSeek URL with Bearer auth + JSON body")
    void chatForwardsBearerAuthToDeepSeek() throws Exception {
        mockServer.expect(requestTo(API_URL))
                .andExpect(method(POST))
                .andExpect(header("Authorization", "Bearer " + API_KEY))
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"model\":\"deepseek-chat\"")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"messages\"")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"role\":\"user\"")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"content\":\"what is M31?\"")))
                .andRespond(withSuccess(DEEPSEEK_OK_BODY, MediaType.APPLICATION_JSON));

        Response<Map<String, Object>> resp = controller.chat(buildChatRequest("what is M31?"));

        assertNotNull(resp, "response must not be null");
        assertEquals("0", resp.getError().getCode(),
                "success path must produce error.code='0' (NO_ERROR); got: " + resp.getError().getCode());
        assertNotNull(resp.getData(), "success path must populate data");
        assertEquals("M31 is a spiral galaxy.", resp.getData().get("content"));
        assertEquals(false, resp.getData().get("cached"),
                "first call must NOT be cached; got: " + resp.getData().get("cached"));
        mockServer.verify();
    }

    @Test
    @DisplayName("R6.98-D #4: identical second call returns CACHE_HIT (cached=true), no upstream call")
    void chatReturnsCachedOnSecondCall() throws Exception {
        mockServer.expect(requestTo(API_URL))
                .andExpect(method(POST))
                .andRespond(withSuccess(DEEPSEEK_OK_BODY, MediaType.APPLICATION_JSON));

        Response<Map<String, Object>> first = controller.chat(buildChatRequest("what is M31?"));
        assertEquals(false, first.getData().get("cached"),
                "first call must NOT be cached");

        Response<Map<String, Object>> second = controller.chat(buildChatRequest("what is M31?"));
        assertEquals(true, second.getData().get("cached"),
                "second call MUST be cached=true (CACHE_HIT path); got: " + second.getData().get("cached"));
        assertEquals("M31 is a spiral galaxy.", second.getData().get("content"));

        mockServer.verify();
    }

    @Test
    @DisplayName("R6.98-D #5: empty API key fails closed with 0500 (no upstream call)")
    void chatFailsClosedWhenApiKeyMissing() throws Exception {
        setField("apiKey", "");

        Response<Map<String, Object>> resp = controller.chat(buildChatRequest("hello"));

        assertEquals("0500", resp.getError().getCode(),
                "missing API key must return code 0500; got: " + resp.getError().getCode());
        assertTrue(resp.getError().getMsg().toLowerCase().contains("api key")
                        || resp.getError().getMsg().toLowerCase().contains("not configured"),
                "error msg must mention missing key; got: " + resp.getError().getMsg());
    }

    @Test
    @DisplayName("R6.98-D #6: upstream 401 → error code 0501 (AUTH_FAILURE)")
    void chatReturns0501On401() throws Exception {
        mockServer.expect(requestTo(API_URL))
                .andExpect(method(POST))
                .andRespond(withStatus(HttpStatus.UNAUTHORIZED));

        Response<Map<String, Object>> resp = controller.chat(buildChatRequest("hello"));

        assertEquals("0501", resp.getError().getCode(),
                "401 must map to 0501 AUTH_FAILURE; got: " + resp.getError().getCode());
        assertTrue(resp.getError().getMsg().toLowerCase().contains("authentication")
                        || resp.getError().getMsg().toLowerCase().contains("api key"),
                "0501 msg must mention auth failure; got: " + resp.getError().getMsg());
    }

    @Test
    @DisplayName("R6.98-D #7: upstream 429 → error code 0429 (RATE_LIMITED)")
    void chatReturns0429On429() throws Exception {
        mockServer.expect(requestTo(API_URL))
                .andExpect(method(POST))
                .andRespond(withStatus(HttpStatus.TOO_MANY_REQUESTS));

        Response<Map<String, Object>> resp = controller.chat(buildChatRequest("hello"));

        assertEquals("0429", resp.getError().getCode(),
                "429 must map to 0429 RATE_LIMITED; got: " + resp.getError().getCode());
        assertTrue(resp.getError().getMsg().toLowerCase().contains("rate limit"),
                "0429 msg must mention rate limit; got: " + resp.getError().getMsg());
    }

    @Test
    @DisplayName("R6.98-D #8: network SocketTimeoutException → error code 0503 (OFFLINE)")
    void chatReturns0503OnNetworkError() throws Exception {
        mockServer.expect(requestTo(API_URL))
                .andExpect(method(POST))
                .andRespond(withException(new java.net.SocketTimeoutException("connect timed out")));

        Response<Map<String, Object>> resp = controller.chat(buildChatRequest("hello"));

        assertEquals("0503", resp.getError().getCode(),
                "network error must map to 0503 OFFLINE; got: " + resp.getError().getCode());
        assertTrue(resp.getError().getMsg().toLowerCase().contains("unreachable")
                        || resp.getError().getMsg().toLowerCase().contains("network"),
                "0503 msg must mention unreachable/network; got: " + resp.getError().getMsg());
    }

    @Test
    @DisplayName("R6.98-D #9: 200 with empty choices → error code 0502 (EMPTY_RESPONSE)")
    void chatReturns0502OnEmptyChoices() throws Exception {
        mockServer.expect(requestTo(API_URL))
                .andExpect(method(POST))
                .andRespond(withSuccess(
                        "{\"id\":\"x\",\"choices\":[]}".getBytes(),
                        MediaType.APPLICATION_JSON));

        Response<Map<String, Object>> resp = controller.chat(buildChatRequest("hello"));

        assertEquals("0502", resp.getError().getCode(),
                "empty choices must map to 0502 EMPTY_RESPONSE; got: " + resp.getError().getCode());
        assertNull(resp.getData(),
                "empty response must NOT have data; got: " + resp.getData());
    }

    @Test
    @DisplayName("R6.98-D #10: response with Content-Type: text/html is rejected (R6.98-B variant)")
    void chatRejectsNonJsonContentType() throws Exception {
        mockServer.expect(requestTo(API_URL))
                .andExpect(method(POST))
                .andRespond(withSuccess(
                        "<html><body>502 Bad Gateway</body></html>".getBytes(),
                        MediaType.TEXT_HTML));

        Response<Map<String, Object>> resp = controller.chat(buildChatRequest("hello"));

        assertNotNull(resp.getError(), "non-JSON response must produce an error response");
        assertFalse("0".equals(resp.getError().getCode()),
                "non-JSON response must NOT silently succeed (code=0); got: " + resp.getError().getCode());
        assertTrue(resp.getError().getMsg().toLowerCase().contains("json")
                        || resp.getError().getMsg().toLowerCase().contains("content")
                        || resp.getError().getMsg().toLowerCase().contains("unexpected"),
                "non-JSON error msg must mention content-type or unexpected response; got: "
                + resp.getError().getMsg());
    }

    @Test
    @DisplayName("R6.98-D #11: GET /status returns configured=true with masked key preview")
    void statusReflectsConfiguredState() {
        Response<Map<String, Object>> resp = controller.status();

        assertEquals("0", resp.getError().getCode());
        assertNotNull(resp.getData());
        assertEquals(true, resp.getData().get("configured"),
                "status must report configured=true when API key is set");
        assertEquals("deepseek-chat", resp.getData().get("model"));
        String preview = (String) resp.getData().get("keyPreview");
        assertNotNull(preview, "keyPreview must be present when configured");
        assertTrue(preview.endsWith("..."), "key preview must end with '...'; got: " + preview);
        assertTrue(preview.length() <= 16,
                "key preview must not leak full key; got length: " + preview.length());
    }

    @Test
    @DisplayName("R6.98-D #12: GET /usage returns current quota + cache stats")
    void usageReturnsCurrentStats() {
        Response<Map<String, Object>> resp = controller.usage();

        assertEquals("0", resp.getError().getCode());
        assertNotNull(resp.getData());
        assertEquals(500, resp.getData().get("dailyQuota"));
        assertEquals(0, resp.getData().get("dailyCount"));
        assertEquals(500, resp.getData().get("dailyRemaining"));
        assertEquals(30, resp.getData().get("cacheTtlMinutes"));
        assertEquals(0, resp.getData().get("cacheEntries"));
    }

    private static Map<String, Object> buildChatRequest(String userContent) {
        Map<String, String> msg = new HashMap<>();
        msg.put("role", "user");
        msg.put("content", userContent);
        Map<String, Object> req = new HashMap<>();
        req.put("messages", List.of(msg));
        return req;
    }

    private void setField(String name, Object value) throws Exception {
        Field f = LlmController.class.getDeclaredField(name);
        f.setAccessible(true);
        f.set(controller, value);
    }
}
