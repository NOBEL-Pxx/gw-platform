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

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

@Configuration
public class ElasticsearchConfig {

    @Value("#{'${spring.elasticsearch.uris}'.split(',')}")
    private List<String> uris;

    @Value("${spring.elasticsearch.username}")
    private String username;

    @Value("${spring.elasticsearch.passwd}")
    private String password;

    // Shared low-level RestClient (v4.12: unified — RestHighLevelClient removed)
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

    // Transport bean: Closeable, closes underlying RestClient
    @Bean(destroyMethod = "close")
    public RestClientTransport restClientTransport() {
        RestClient restClient = buildRestClientBuilder().build();
        return new RestClientTransport(restClient, new JacksonJsonpMapper());
    }

    // ElasticsearchClient 8.x — unified client (v4.12: RestHighLevelClient removed)
    @Bean
    public ElasticsearchClient elasticsearchClient(RestClientTransport transport) {
        return new ElasticsearchClient(transport);
    }
}
