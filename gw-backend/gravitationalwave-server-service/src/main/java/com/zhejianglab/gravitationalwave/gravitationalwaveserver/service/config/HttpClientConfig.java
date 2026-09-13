package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import jakarta.annotation.PostConstruct;
import org.apache.hc.client5.http.DnsResolver;
import org.apache.hc.client5.http.config.ConnectionConfig;
import org.apache.hc.client5.http.config.RequestConfig;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.client5.http.ssl.SSLConnectionSocketFactory;
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
 * <p><b>R6.98-D</b>: dedicated {@code llmRestClient} bean (api.deepseek.com — TLS
 * pinning only) and {@code chinaVoRestClient} bean (hips.china-vo.org — TLS
 * pinning AND DNS resolver pinning).
 *
 * <p><b>Coexistence with HttpClient 4.x</b>: Elasticsearch low-level RestClient
 * uses {@code org.apache.http.*} (4.x); this bean uses {@code org.apache.hc.client5.*}
 * (5.x). Different packages, both jars coexist on classpath.
 *
 * <p><b>Iron rules established here</b>:
 * <ul>
 *   <li><b>R6.98-A</b>: all outbound HTTP MUST use a Spring-managed
 *       {@link RestClient} bean -- no ad-hoc {@code new RestTemplate()} inside
 *       service methods.</li>
 *   <li><b>R6.98-B</b>: max total connections = 100, max per-route = 20.
 *       Matches ElasticsearchConfig defaults.</li>
 *   <li><b>R6.98-D</b>: TLS pinning for outbound HTTPS to third-party services
 *       MUST go through a dedicated pinned {@code CloseableHttpClient}. For
 *       china-vo.org specifically, DNS resolver pinning is ALSO mandatory
 *       (mutable-DNS attack surface on a 3rd-party subdomain).</li>
 * </ul>
 *
 * <p><b>V1 markers</b>:
 * <ul>
 *   <li>{@code "R6.98: HttpClientConfig initialized"} — bean construction.</li>
 *   <li>{@code "R6.98: TLS pinning active for api.deepseek.com (cert SHA-256: <hex>)"}
 *       — logged by {@link TlsPinningHttpClientFactory#build(String, String)}
 *       when the dedicated LLM client is built with pinning enabled.</li>
 *   <li>{@code "R6.98: TLS pinning active for hips.china-vo.org (cert SHA-256: <hex>)"}
 *       — same, for chinaVoRestClient when pinning is enabled.</li>
 *   <li>{@code "R6.98-D: DNS resolver pinned for hips.china-vo.org -> [<ip1>, <ip2>]"}
 *       — logged by {@link ChinaVoDnsResolver#forHost(String)} at startup.</li>
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

    /**
     * R6.98-D: dedicated {@link RestClient} bean for the china-vo.org channel
     * ({@code hips.china-vo.org} and its {@code /generate} endpoints).
     *
     * <p>Two-layer defense compared to {@link #llmRestClient}:
     * <ol>
     *   <li><b>TLS pubkey pinning</b> (R6.98-A): when {@code chinavo.api.pinned-cert-sha256}
     *       is configured, uses {@link TlsPinningHttpClientFactory} with a SPKI
     *       SHA-256 allowlist. Falls back to the JVM default truststore when
     *       unset (TOFU capture pending on first prod deploy) with a clear
     *       log warning.</li>
     *   <li><b>DNS resolver pinning</b> (R6.98-D): always installs a
     *       {@link ChinaVoDnsResolver} that resolves {@code hips.china-vo.org}
     *       to its startup-time IPs. ALL subsequent requests through this bean
     *       route through the pinned IPs — preventing DNS rebinding attacks
     *       where the resolver returns a different IP between TLS handshake
     *       and request body transmission.</li>
     * </ol>
     *
     * <p>The bean intentionally fails fast if {@link ChinaVoDnsResolver#forHost(String)}
     * cannot resolve the host (no silent fallback to system resolver — that
     * would re-open the rebinding attack surface). To bypass pinning in dev
     * environments where china-vo.org is unreachable, set
     * {@code chinavo.dns.pin.enabled=false} in application properties.
     *
     * @param pinnedCertSha256 SHA-256 SPKI fingerprint for hips.china-vo.org.
     *                        If blank, falls back to JVM default truststore
     *                        (with warning). DNS pinning remains active.
     */
    @Bean
    public RestClient chinaVoRestClient(
            @Value("${chinavo.api.pinned-cert-sha256:}") String pinnedCertSha256) {
        // R6.98-D: ALWAYS install DNS pinning for china-vo.org — even when
        // TLS pinning is unset. DNS rebinding is a separate attack vector.
        DnsResolver dnsResolver = ChinaVoDnsResolver.forHipsChinaVoOrg();

        CloseableHttpClient client;
        if (pinnedCertSha256 != null && !pinnedCertSha256.isBlank()) {
            // R6.98-D: TLS pinning + DNS pinning together via TlsPinningHttpClientFactory.
            client = TlsPinningHttpClientFactory.build(
                    pinnedCertSha256, "hips.china-vo.org", dnsResolver);
        } else {
            log.warn("R6.98-D: chinavo.api.pinned-cert-sha256 not configured; "
                    + "chinaVoRestClient using DNS pinning ONLY (no TLS pinning — "
                    + "dev mode — capture cert SHA-256 on first prod deploy)");
            // Build a custom client with DNS resolver override but JVM default SSL.
            client = buildChinaVoClientWithoutTlsPin(dnsResolver);
        }

        return RestClient.builder()
                .requestFactory(new HttpComponentsClientHttpRequestFactory(client))
                .build();
    }

    /**
     * Build a {@link CloseableHttpClient} for china-vo.org with DNS resolver
     * override but JVM-default SSL truststore (no SPKI pinning). Used as the
     * fallback path when {@code chinavo.api.pinned-cert-sha256} is unset.
     */
    private CloseableHttpClient buildChinaVoClientWithoutTlsPin(DnsResolver dnsResolver) {
        PoolingHttpClientConnectionManager connManager = PoolingHttpClientConnectionManagerBuilder.create()
                .setMaxConnTotal(MAX_CONN_TOTAL)
                .setMaxConnPerRoute(MAX_CONN_PER_ROUTE)
                .setDefaultConnectionConfig(ConnectionConfig.custom()
                        .setConnectTimeout(CONNECT_TIMEOUT)
                        .setSocketTimeout(RESPONSE_TIMEOUT)
                        .setTimeToLive(CONN_KEEP_ALIVE)
                        .build())
                .setDnsResolver(dnsResolver)
                // JVM default SSL socket factory — used here as the fallback
                // when SPKI pin isn't configured yet.
                .setSSLSocketFactory(SSLConnectionSocketFactory.getSocketFactory())
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
}
