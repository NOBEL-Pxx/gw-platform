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
 * <p><b>Phase 1+2 scope (this file)</b>: infrastructure only. Beans are registered
 * but no consumer exists yet. Behavior change: zero. Future R6.98 Phase 3+
 * migrations will switch individual consumers (ImageCutoutDataSet, AuditService,
 * LlmController, PipelineProxyController) from {@code RestTemplate} to the
 * {@code RestClient} bean exposed here.
 *
 * <p><b>Coexistence with HttpClient 4.x</b>: Elasticsearch low-level RestClient
 * uses {@code org.apache.http.*} (4.x); this bean uses {@code org.apache.hc.client5.*}
 * (5.x). Different packages, both jars coexist on classpath.
 *
 * <p><b>Iron rules established here</b>:
 * <ul>
 *   <li><b>R6.98-A</b> (correctness): All outbound HTTP MUST use the shared
 *       {@code CloseableHttpClient} bean via {@code RestClient} -- no ad-hoc
 *       {@code HttpClients.createDefault()} inside service methods (avoids
 *       per-call connection pool allocation + connection leaks).</li>
 *   <li><b>R6.98-B</b> (perf): max total connections = 100, max per-route = 20.
 *       Matches ElasticsearchConfig defaults. Sized for china-vo.org (3 cutout
 *       endpoints) + api.deepseek.com (1 endpoint) traffic pattern.</li>
 * </ul>
 *
 * <p><b>V1 marker</b>: {@code "R6.98: HttpClientConfig initialized"} logged at
 * {@code @PostConstruct} -- confirms bean construction at container startup;
 * searchable in container logs via {@code zsmoke check_marker_log}.
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
     * legacy {@code RestTemplate} for future R6.98 migrations.
     */
    @Bean
    public RestClient sharedRestClient(CloseableHttpClient httpClient) {
        return RestClient.builder()
                .requestFactory(new HttpComponentsClientHttpRequestFactory(httpClient))
                .build();
    }
}
