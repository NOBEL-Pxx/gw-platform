package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.json.jackson.JacksonJsonpMapper;
import co.elastic.clients.transport.rest_client.RestClientTransport;
import org.apache.http.HttpHost;
import org.apache.http.auth.AuthScope;
import org.apache.http.auth.UsernamePasswordCredentials;
import org.apache.http.client.CredentialsProvider;
import org.apache.http.impl.client.BasicCredentialsProvider;
import org.apache.http.impl.nio.reactor.IOReactorConfig;
import org.elasticsearch.client.RestClient;
import org.elasticsearch.client.RestClientBuilder;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;

import org.apache.http.message.BasicHeader;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.ArrayList;
import java.util.List;

@Configuration
public class ElasticsearchConfig {

    private static String sha256Short(String s) {
        if (s == null) return "null";
        try {
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256")
                .digest(s.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest).substring(0, 12);
        } catch (java.security.NoSuchAlgorithmException e) {
            return "err";
        }
    }

    @Value("#{'${spring.elasticsearch.uris}'.split(',')}")
    private List<String> uris;

    @Value("${spring.elasticsearch.username}")
    private String username;

    @Value("${spring.elasticsearch.password}")
    private String password;
    private static final Logger log = LoggerFactory.getLogger(ElasticsearchConfig.class);

    // Shared low-level RestClient (v4.12: unified - RestHighLevelClient removed)
    private RestClientBuilder buildRestClientBuilder() {
        List<HttpHost> hosts = new ArrayList<>();
        for (String uri : uris) {
            hosts.add(HttpHost.create(uri));
        }

        CredentialsProvider credentialsProvider = new BasicCredentialsProvider();
        credentialsProvider.setCredentials(AuthScope.ANY, new UsernamePasswordCredentials(username, password));

        return RestClient.builder(hosts.toArray(new HttpHost[]{}))
                .setHttpClientConfigCallback(httpClientBuilder -> {
                    httpClientBuilder.setDefaultCredentialsProvider(credentialsProvider);
                    httpClientBuilder.disableAuthCaching();
                    httpClientBuilder.setDefaultIOReactorConfig(IOReactorConfig.custom().setSoKeepAlive(true).build());
                    httpClientBuilder.setKeepAliveStrategy((response, context) -> Duration.ofMinutes(3).toMillis());
                    return httpClientBuilder;
                });
    }


    // R6.99-D: provide explicit RestClient bean with preemptive Basic auth via default headers.
    // This OVERRIDES Spring Boot's auto-configured RestClient (@ConditionalOnMissingBean).
    // Preemptive Basic auth guarantees the Authorization header is sent on EVERY request,
    // bypassing the challenge-response loop that the Apache HttpAsyncClient 8.15.0 has issues with.
    @Primary
    @Bean(destroyMethod = "close")
    public RestClient elasticsearchRestClient() {
        // Precompute preemptive Basic auth header (length+sha logged on bean construction; never echoed in cleartext)
        final String basicAuthHeader = "Basic " + Base64.getEncoder().encodeToString(
                (username + ":" + password).getBytes(StandardCharsets.UTF_8));
        log.info("elasticsearchRestClient bean created with preemptive Basic auth; ES username length={} sha={} | password length={} sha={}",
            username == null ? -1 : username.length(),
            sha256Short(username),
            password == null ? -1 : password.length(),
            sha256Short(password));

        return buildRestClientBuilder()
                .setDefaultHeaders(new org.apache.http.Header[]{
                        new BasicHeader("Authorization", basicAuthHeader)
                })
                .build();
    }

    // R6.99-D: @Primary so this wins over auto-config's beans
    @Primary
    @Bean(destroyMethod = "close")
    public RestClientTransport restClientTransport() {
        RestClient restClient = buildRestClientBuilder().build();
        return new RestClientTransport(restClient, new JacksonJsonpMapper());
    }

    // R6.99-D: @Primary so this wins over auto-config's bean
    @Primary
    @Bean
    public ElasticsearchClient elasticsearchClient(RestClientTransport transport) {
        return new ElasticsearchClient(transport);
    }
}
