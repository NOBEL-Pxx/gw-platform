package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import jakarta.annotation.PostConstruct;
import org.apache.hc.client5.http.config.ConnectionConfig;
import org.apache.hc.client5.http.config.RequestConfig;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.core5.util.TimeValue;
import org.apache.hc.core5.util.Timeout;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * R6.98 Phase 1+2: shared HttpClient 5 + RestClient beans for outbound HTTP calls.
 *
 * <p><b>Why HttpClient 5 (not Spring RestTemplate)?</b> Spring's {@code RestTemplate}
 * does not expose {@code SSLContext} or {@code DnsResolver}, both of which are
 * required for the deferred R6.98 hardening items:
 * <ul>
 *   <li><b>O-4 TLS pubkey pinning</b> -- runtime auto-reject certs whose pubkey
 *       SHA-256 isn't in our allowlist (china-vo.org, api.deepseek.com).
 *       Requires custom {@code X509TrustManager} + {@code SSLContext} injection
 *       into the HttpClient -- only possible with low-level HttpClient API.</li>
 *   <li><b>O-10 DNS pinning</b> -- runtime lock DNS resolution to known IPs.
 *       Requires Apache HttpClient {@code DnsResolver} override.</li>
 * </ul>
 *
 * <p><b>Phase 1+2 scope</b>: shared {@code CloseableHttpClient} + {@code RestClient}
 * beans (general-purpose). Behavior change: zero.
 *
 * <p><b>R6.98-D</b>: dedicated {@code llmRestClient} bean for the LLM channel
 * (api.deepseek.com). Uses {@link TlsPinningHttpClientFactory} when
 * {@code deepseek.api.pinned-cert-sha256} is configured; otherwise falls back
 * to the shared client with a clear log warning. Isolation: TLS pinning for
 * api.deepseek.com MUST NOT bleed into other consumers (china-vo.org etc.).
 *
 * <p><b>Coexistence with HttpClient 4.x</b>: Elasticsearch low-level RestClient
 * uses {@code org.apache.http.*} (4.x); this bean uses {@code org.apache.hc.client5.*}
 * (5.x). Different packages, both jars coexist on classpath.
 *
 * <p><b>Iron rules established here</b>:
 * <ul>
 *   <li><b>R6.98-A</b>: all outbound HTTP MUST use the shared
 *       {@code CloseableHttpClient} bean via {@code RestClient} -- no ad-hoc
 *       {@code HttpClients.createDefault()} inside service methods.</li>
 *   <li><b>R6.98-B</b>: max total connections = 100, max per-route = 20.
 *       Matches ElasticsearchConfig defaults.</li>
 *   <li><b>R6.98-D</b>: TLS pinning for outbound HTTPS to third-party services
 *       MUST go through a dedicated pinned {@code CloseableHttpClient}. The
 *       dedicated {@code llmRestClient} bean is wired via
 *       {@link TlsPinningHttpClientFactory} when a pinned SHA-256 is configured.</li>
 * </ul>
 *
 * <p><b>V1 markers</b>:
 * <ul>
 *   <li>{@code "R6.98: HttpClientConfig initialized"} — bean construction.</li>
 *   <li>{@code "R6.98: TLS pinning active for api.deepseek.com (cert SHA-256: <hex>)"}
 *       — logged by {@link TlsPinningHttpClientFactory#build(String, String)}
 *       when the dedicated LLM client is built with pinning enabled.</li>
 * </ul>
 */
@Configuration
public class HttpClientConfig {

    private static final Logger log = LoggerFactory.getLogger(HttpClientConfig.class);

    // Pool sizing -- matches ElasticsearchConfig defaults
    private static final int MAX_CONN_TOTAL = 100;
    private static final int MAX_CONN_PER_ROUTE = 20;

    // Timeouts -- unified default; consumers can override per-request via RestClient
    private static final Timeout CONNECT_TIMEOUT = Timeout.ofSeconds(10);
    private static final Timeout RESPONSE_TIMEOUT = Timeout.ofSeconds(30);

    // Keep-alive -- 3 minutes (matches ElasticsearchConfig keep-alive strategy)
    private static final TimeValue CONN_KEEP_ALIVE = TimeValue.ofMinutes(3);

    @PostConstruct
    void logInit() {
        log.info("R6.98: HttpClientConfig initialized (pool=max={}/route={}, connect={}ms, response={}ms)",
                MAX_CONN_TOTAL, MAX_CONN_PER_ROUTE,
                CONNECT_TIMEOUT.toMilliseconds(), RESPONSE_TIMEOUT.toMilliseconds());
    }

    @Bean(destroyMethod = "close")
    public CloseableHttpClient sharedHttpClient() {
        PoolingHttpClientConnectionManager connManager = PoolingHttpClientConnectionManagerBuilder.create()
                .setMaxConnTotal(MAX_CONN_TOTAL)
                .setMaxConnPerRoute(MAX_CONN_PER_ROUTE)
                .setDefaultConnectionConfig(ConnectionConfig.custom()
                        .setConnectTimeout(CONNECT_TIMEOUT)
                        .setSocketTimeout(RESPONSE_TIMEOUT)
                        .setTimeToLive(CONN_KEEP_ALIVE)
                        .build())
                .build();

        RequestConfig requestConfig = RequestConfig.custom()
                .setConnectionRequestTimeout(CONNECT_TIMEOUT)
                .setResponseTimeout(RESPONSE_TIMEOUT)
                .build();

        return HttpClients.custom()
                .setConnectionManager(connManager)
                .setDefaultRequestConfig(requestConfig)
                .setKeepAliveStrategy((response, context) -> CONN_KEEP_ALIVE)
                .build();
    }

    /**
     * Spring's modern {@code RestClient} wrapper around the shared HttpClient 5.
     * Provides builder-pattern API + auto-content-type negotiation. Replaces
     * legacy {@code RestTemplate} for R6.98 Phase 3+ migrations.
     */
    @Bean
    public RestClient sharedRestClient(CloseableHttpClient httpClient) {
        return RestClient.builder()
                .requestFactory(new HttpComponentsClientHttpRequestFactory(httpClient))
                .build();
    }

    /**
     * R6.98-D: dedicated {@link RestClient} bean for the LLM channel
     * (api.deepseek.com).
     *
     * <p>Uses {@link TlsPinningHttpClientFactory} to build a {@link CloseableHttpClient}
     * whose {@code SSLContext} enforces SPKI SHA-256 pinning for api.deepseek.com.
     * If {@code deepseek.api.pinned-cert-sha256} is not configured (TOFU
     * capture pending on first deploy), falls back to the shared client with
     * a clear log warning so dev mode still works.
     *
     * <p>Why a dedicated bean (not shared)?
     * <ul>
     *   <li>TLS pinning for api.deepseek.com must NOT bleed into other consumers.</li>
     *   <li>The pinned client's connection pool is logically separate from the
     *       general shared pool.</li>
     *   <li>Future per-host overrides (DNS pinning for china-vo.org, etc.) plug
     *       in here as additional dedicated beans without touching the shared one.</li>
     * </ul>
     *
     * @param httpClient The shared {@link CloseableHttpClient} (used as fallback
     *                   when pinning is not yet configured).
     * @param pinnedCertSha256 SHA-256 SPKI fingerprint for api.deepseek.com. If
     *                        blank, the bean falls back to the shared client.
     */
    @Bean
    public RestClient llmRestClient(
            CloseableHttpClient httpClient,
            @Value("${deepseek.api.pinned-cert-sha256:}") String pinnedCertSha256) {
        if (pinnedCertSha256 == null || pinnedCertSha256.isBlank()) {
            log.warn("R6.98-D: deepseek.api.pinned-cert-sha256 not configured; "
                    + "llmRestClient falling back to sharedRestClient WITHOUT TLS pinning "
                    + "(dev mode — capture cert SHA-256 on first prod deploy)");
            return RestClient.builder()
                    .requestFactory(new HttpComponentsClientHttpRequestFactory(httpClient))
                    .build();
        }
        CloseableHttpClient pinned = TlsPinningHttpClientFactory.build(
                pinnedCertSha256, "api.deepseek.com");
        return RestClient.builder()
                .requestFactory(new HttpComponentsClientHttpRequestFactory(pinned))
                .build();
    }
}
