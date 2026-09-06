package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.util;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.io.IOException;

@Component
public class ConnectionCheckUtil {

    private final ElasticsearchClient elasticsearchClient;

    @Autowired
    public ConnectionCheckUtil(ElasticsearchClient elasticsearchClient) {
        this.elasticsearchClient = elasticsearchClient;
    }

    public boolean isElasticsearchUp() {
        try {
            boolean pingResult = elasticsearchClient.ping().value();
            System.out.println("Elasticsearch ping: " + pingResult);
            return pingResult;
        } catch (IOException e) {
            e.printStackTrace();
            return false;
        }
    }
}