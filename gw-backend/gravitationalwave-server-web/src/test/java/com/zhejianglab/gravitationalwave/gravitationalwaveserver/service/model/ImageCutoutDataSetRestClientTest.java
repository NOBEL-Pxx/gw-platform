package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;
import static org.springframework.http.HttpMethod.GET;
import static org.springframework.http.HttpMethod.POST;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * R6.98-D (ImageCutoutDataSet migration): tests verifying ImageCutoutDataSet
 * uses the dedicated TLS-pinned + DNS-pinned {@link RestClient} bean for
 * hips.china-vo.org (NOT a local {@code RestTemplate}).
 *
 * <p><b>Iron rules</b>:
 * <ul>
 *   <li><b>R6.98-A</b>: all outbound HTTP MUST use a Spring-managed {@link RestClient}
 *       bean — no ad-hoc {@code new RestTemplate()}. ImageCutoutDataSet uses a
 *       DEDICATED {@code chinaVoRestClient} bean (not {@code sharedRestClient}) because
 *       china-vo.org needs both TLS pinning AND DNS resolver pinning (R6.98-D).</li>
 *   <li><b>R6.98-D</b> (TLS + DNS pinning variant): outbound HTTPS to
 *       {@code hips.china-vo.org} MUST go through a pinned {@code CloseableHttpClient}
 *       built by {@link com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config.TlsPinningHttpClientFactory}
 *       AND a {@link org.apache.hc.core5.http.DnsResolver} override that resolves
 *       {@code hips.china-vo.org} to a known IP at startup. This prevents both
 *       MITM via misissued cert AND DNS rebinding attacks.</li>
 * </ul>
 *
 * <p><b>Pre-existing defenses preserved</b> (see also
 * {@link ImageCutoutDataSetDownloadTest} for the 13-case static-helper suite):
 * <ul>
 *   <li>R6.95-A: SSRF — {@code validateImageUrl} rejects hosts not ending in
 *       {@code .china-vo.org} (suffix- and prefix-collision safe).</li>
 *   <li>R6.96-O6: maxOutputSize (50 MiB) pre-fetch Content-Length + post-fetch backstop.</li>
 *   <li>R6.96-O7: DNS-rebinding — {@code validateResolvedIps} rejects private IPs
 *       (loopback, site-local, link-local, CGNAT, IPv6 ULA).</li>
 *   <li>R6.95-B: path-traversal — {@code resolveCanonicalOutputPath} canonicalizes
 *       the output path against {@code outputBasedir}.</li>
 * </ul>
 *
 * <p>Approach: Spring's {@link MockRestServiceServer} bound to a fresh
 * {@link RestClient.Builder}. TLS pinning and DNS pinning are NOT exercised
 * here — they are tested separately in {@code TlsPinningHttpClientFactoryTest}
 * and {@code ChinaVoDnsResolverTest}. This test focuses on the wire-level
 * contract (URL, method, headers, body) and the pre-existing R6.95/96 defense
 * paths after the RestTemplate → RestClient migration.
 */
class ImageCutoutDataSetRestClientTest {

    private static final String HIPS_BASE = "https://hips.china-vo.org";
    private static final String LOGIN_URL = HIPS_BASE + "/generate/login";
    private static final String LIST_DATASETS_URL = HIPS_BASE + "/generate/list-dataset";
    private static final String USERNAME = "test-user";
    private static final String PASSWORD = "test-pass";
    private static final long MAX_OUTPUT_SIZE = 5_242_880L; // 5 MiB (smaller than default for test speed)

    /**
     * Shared temp directory across setUp + tests. Required because
     * {@code outputBasedir} is set to {@code tempDir.toString()} in setUp() and
     * download() resolves its output path against outputBasedir — they MUST be
     * the same directory tree for the path-traversal check to pass.
     */
    @TempDir
    Path tempDir;

    private RestClient restClient;
    private MockRestServiceServer mockServer;
    private ImageCutoutDataSet dataSet;

    @BeforeEach
    void setUp() throws Exception {
        RestClient.Builder builder = RestClient.builder();
        mockServer = MockRestServiceServer.bindTo(builder).build();
        restClient = builder.build();

        // R6.98-D: constructor injection of dedicated chinaVoRestClient bean.
        dataSet = new ImageCutoutDataSet(restClient);

        setField("username", USERNAME);
        setField("password", PASSWORD);
        setField("outputBasedir", tempDir.toString());
        setField("maxOutputSize", MAX_OUTPUT_SIZE);

        // @PostConstruct init() — logs V1 marker. For the migrated bean, timeouts
        // come from the shared HttpClient pool, so the migrated init() just logs
        // the marker.
        Method init = ImageCutoutDataSet.class.getDeclaredMethod("init");
        init.setAccessible(true);
        init.invoke(dataSet);
    }

    // ─── Iron rule R6.98-A: no RestTemplate field ───────────────────────────

    @Test
    @DisplayName("R6.98-D #1: RestTemplate field removed (R6.98-A iron rule)")
    void restTemplateFieldRemoved() {
        boolean hasRestTemplate = false;
        for (Field f : ImageCutoutDataSet.class.getDeclaredFields()) {
            if (f.getType().getSimpleName().equals("RestTemplate")) {
                hasRestTemplate = true;
                break;
            }
        }
        assertFalse(hasRestTemplate,
                "R6.98-A: ImageCutoutDataSet must not declare a RestTemplate field; "
                + "use dedicated chinaVoRestClient bean via constructor injection");
    }

    @Test
    @DisplayName("R6.98-D #2: ImageCutoutDataSet declares a final RestClient field (R6.98-A wiring)")
    void constructorInjectsRestClient() {
        boolean hasRestClientField = false;
        for (Field f : ImageCutoutDataSet.class.getDeclaredFields()) {
            if (f.getType().getSimpleName().equals("RestClient")) {
                hasRestClientField = true;
                assertTrue(java.lang.reflect.Modifier.isFinal(f.getModifiers()),
                        "R6.98-A: RestClient field must be final (constructor injection)");
                break;
            }
        }
        assertTrue(hasRestClientField,
                "R6.98-A: ImageCutoutDataSet must declare a RestClient field for injection");
    }

    // ─── Wire-level contract: login (POST /generate/login) ─────────────────

    @Test
    @DisplayName("R6.98-D #3: auth() POSTs JSON body to /generate/login")
    void authPostsToLoginUrl() throws Exception {
        mockServer.expect(requestTo(LOGIN_URL))
                .andExpect(method(POST))
                .andExpect(org.springframework.test.web.client.match.MockRestRequestMatchers
                        .content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(org.springframework.test.web.client.match.MockRestRequestMatchers
                        .content().string(org.hamcrest.Matchers.containsString("\"username\":\"" + USERNAME + "\"")))
                .andExpect(org.springframework.test.web.client.match.MockRestRequestMatchers
                        .content().string(org.hamcrest.Matchers.containsString("\"password\":\"" + PASSWORD + "\"")))
                .andRespond(withSuccess("{\"token\":\"jwt-abc-123\"}", MediaType.APPLICATION_JSON));

        // Reset token state to force a real auth() round-trip.
        setField("token", "");

        dataSet.auth();

        // R6.90 B5: token is stored on successful auth (idempotent path).
        assertTrue(dataSet.authorized(), "auth() must store token on 200 success");
        mockServer.verify();
    }

    @Test
    @DisplayName("R6.98-D #4: auth() clears token when upstream returns non-200")
    void authClearsTokenOnError() throws Exception {
        // Token starts empty (setUp() default). The idempotent fast path
        // checks `!token.isEmpty() && authorized()`, so an empty token
        // forces the network round-trip — which we mock to fail with 401.
        // We deliberately do NOT pre-set a token, because the fast path
        // would otherwise short-circuit and never hit the catch block.

        mockServer.expect(requestTo(LOGIN_URL))
                .andExpect(method(POST))
                .andRespond(withStatus(HttpStatus.UNAUTHORIZED));

        dataSet.auth();

        // R6.95-B pattern: failed auth leaves token empty.
        assertFalse(dataSet.authorized(), "auth() must clear token on non-200");
        Field tokenField = ImageCutoutDataSet.class.getDeclaredField("token");
        tokenField.setAccessible(true);
        assertEquals("", tokenField.get(dataSet),
                "token must be empty string after auth failure; got: " + tokenField.get(dataSet));
        mockServer.verify();
    }

    // ─── Wire-level contract: download (GET /generate) ──────────────────────

    @Test
    @DisplayName("R6.98-D #5: download() GETs /generate with Bearer auth + query params, then fetches image_path")
    void downloadGetsGenerateWithBearerAuth() throws Exception {
        // Pre-set token so we can assert the Authorization header exactly.
        setField("token", "test-token-123");

        Metadata metadata = buildMetadata();

        String generateUrl = HIPS_BASE + "/generate?dataset_name=test&format=PNG"
                + "&ra=10.0&dec=20.0&fov=1.0&width=512&height=512";
        String downloadUrl = "https://hips.china-vo.org/dl/test.fits";
        // Mock BOTH requests: the /generate call returns the JSON pointer,
        // then /dl/test.fits returns the actual image bytes (1KB dummy).
        byte[] imageBytes = new byte[1024];
        for (int i = 0; i < imageBytes.length; i++) imageBytes[i] = (byte) i;

        mockServer.expect(requestTo(generateUrl))
                .andExpect(method(GET))
                .andExpect(org.springframework.test.web.client.match.MockRestRequestMatchers
                        .header("Authorization", "Bearer test-token-123"))
                .andRespond(withSuccess(
                        "{\"image_path\":\"" + downloadUrl + "\"}", MediaType.APPLICATION_JSON));
        mockServer.expect(requestTo(downloadUrl))
                .andExpect(method(GET))
                .andRespond(withSuccess(imageBytes, MediaType.APPLICATION_OCTET_STREAM));

        // download() should complete successfully and write the file.
        String output = tempDir.resolve("test.png").toString();
        dataSet.download(output, "PNG", metadata);

        // Verify both expected requests fired and the file landed on disk.
        mockServer.verify();
        assertTrue(java.nio.file.Files.exists(java.nio.file.Paths.get(output)),
                "download() must write the image file to disk; got: " + output);
        assertEquals(imageBytes.length, java.nio.file.Files.size(java.nio.file.Paths.get(output)),
                "file size must match the mock response body");
    }

    // ─── Pre-existing R6.95-A SSRF defense preserved ───────────────────────

    @Test
    @DisplayName("R6.98-D #6: R6.95-A preserved — image_path in body pointing to foreign host is rejected")
    void downloadRejectsForeignHostImagePath() throws Exception {
        setField("token", "test-token-123");

        Metadata metadata = buildMetadata();

        String generateUrl = HIPS_BASE + "/generate?dataset_name=test&format=PNG"
                + "&ra=10.0&dec=20.0&fov=1.0&width=512&height=512";

        // image_path in JSON body points to evil.com — R6.95-A validateImageUrl
        // must reject (host suffix is not .china-vo.org).
        String jsonBody = "{\"image_path\":\"https://evil.com/steal-bearer\"}";

        mockServer.expect(requestTo(generateUrl))
                .andExpect(method(GET))
                .andRespond(withSuccess(jsonBody, MediaType.APPLICATION_JSON));

        try {
            dataSet.download(tempDir.resolve("test.png").toString(), "PNG", metadata);
            fail("R6.95-A: download must reject foreign host image_path");
        } catch (Exception e) {
            assertTrue(e.getMessage().contains("R6.95-A") || e.getMessage().contains("non-allowed host"),
                    "R6.95-A: error must mention non-allowed host; got: " + e.getMessage());
        }
        // Only ONE request was made (to /generate), not two — verified by no AssertionError.
    }

    // ─── Pre-existing R6.96-O6 maxOutputSize pre-fetch (Content-Length) ────

    @Test
    @DisplayName("R6.98-D #7: R6.96-O6 preserved — Content-Length > maxOutputSize rejected pre-fetch")
    void downloadEnforcesContentLengthCap() throws Exception {
        setField("token", "test-token-123");

        Metadata metadata = buildMetadata();

        String generateUrl = HIPS_BASE + "/generate?dataset_name=test&format=PNG"
                + "&ra=10.0&dec=20.0&fov=1.0&width=512&height=512";
        String downloadUrl = "https://hips.china-vo.org/dl/test.fits";

        // Use a body of 1024 bytes so the explicit Content-Length header is not
        // silently overridden by MockRestServiceServer's computed length.
        byte[] body = new byte[1024];

        HttpHeaders dlHeaders = new HttpHeaders();
        // Declare a size larger than the 5 MiB cap we set in setUp().
        dlHeaders.setContentLength(MAX_OUTPUT_SIZE + 1024);

        mockServer.expect(requestTo(generateUrl))
                .andExpect(method(GET))
                .andRespond(withSuccess(
                        "{\"image_path\":\"" + downloadUrl + "\"}", MediaType.APPLICATION_JSON));
        mockServer.expect(requestTo(downloadUrl))
                .andExpect(method(GET))
                .andRespond(withStatus(HttpStatus.OK).headers(dlHeaders).body(body));

        try {
            dataSet.download(tempDir.resolve("test.png").toString(), "PNG", metadata);
            fail("R6.96-O6: download must reject Content-Length > maxOutputSize pre-fetch");
        } catch (Exception e) {
            assertTrue(e.getMessage().contains("R6.96-O6") || e.getMessage().contains("exceeds"),
                    "R6.96-O6: error must mention exceeds/cap; got: " + e.getMessage());
        }
        mockServer.verify();
    }

    // ─── Wire-level contract: getDatasets (GET /generate/list-dataset) ──────

    @Test
    @DisplayName("R6.98-D #8: getDatasets() GETs /generate/list-dataset and returns array")
    void getDatasetsReturnsStringArray() {
        mockServer.expect(requestTo(LIST_DATASETS_URL))
                .andExpect(method(GET))
                .andRespond(withSuccess("[\"datasetA\",\"datasetB\"]", MediaType.APPLICATION_JSON));

        String[] datasets = dataSet.getDatasets();

        assertNotNull(datasets, "getDatasets must return non-null array");
        assertEquals(2, datasets.length, "must return 2 datasets");
        assertEquals("datasetA", datasets[0]);
        assertEquals("datasetB", datasets[1]);
        mockServer.verify();
    }

    // ─── Token storage on 200 success (preserved semantics) ────────────────

    @Test
    @DisplayName("R6.98-D #9: auth() stores JWT token from response body on 200")
    void authStoresTokenFromResponse() throws Exception {
        Field tokenField = ImageCutoutDataSet.class.getDeclaredField("token");
        tokenField.setAccessible(true);

        mockServer.expect(requestTo(LOGIN_URL))
                .andExpect(method(POST))
                .andRespond(withSuccess("{\"token\":\"jwt-xyz-789\"}", MediaType.APPLICATION_JSON));

        // Reset token state.
        tokenField.set(dataSet, "");

        dataSet.auth();

        assertEquals("jwt-xyz-789", tokenField.get(dataSet),
                "token must be parsed from response body; got: " + tokenField.get(dataSet));
        assertTrue(dataSet.authorized(), "dataSet must report authorized=true");
        mockServer.verify();
    }

    // ─── Idempotent auth: skip network call when token valid ───────────────

    @Test
    @DisplayName("R6.98-D #10: auth() is idempotent — skips network when token already valid")
    void authIsIdempotentWhenTokenValid() throws Exception {
        // Pre-set a valid-looking token so auth() fast-paths without a network call.
        Field tokenField = ImageCutoutDataSet.class.getDeclaredField("token");
        tokenField.setAccessible(true);
        tokenField.set(dataSet, "valid-jwt-from-previous-call");

        // No mockServer.expect() — if auth() makes a network call, mockServer.verify()
        // would either error (unexpected request) or the test would observe it.
        dataSet.auth();

        // Token unchanged (idempotent).
        assertEquals("valid-jwt-from-previous-call", tokenField.get(dataSet),
                "idempotent auth must not overwrite existing token; got: " + tokenField.get(dataSet));
        // No requests were made — verified by no AssertionError from mockServer.
    }

    // ─── helpers ───────────────────────────────────────────────────────────

    private void setField(String name, Object value) throws Exception {
        Field f = ImageCutoutDataSet.class.getDeclaredField(name);
        f.setAccessible(true);
        f.set(dataSet, value);
    }

    /** Build a minimal Metadata for the download() entry point. */
    private Metadata buildMetadata() {
        Metadata m = new Metadata();
        m.setDataset_name("test");
        m.setRa(10.0);
        m.setDec(20.0);
        m.setFov(1.0);
        m.setWidth(512);
        m.setHeight(512);
        return m;
    }
}
