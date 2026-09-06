package com.zhejianglab.gravitationalwave.starter;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.data.elasticsearch.repository.config.EnableElasticsearchRepositories;
import org.springframework.data.mongodb.repository.config.EnableMongoRepositories;


@SpringBootApplication(exclude={DataSourceAutoConfiguration.class})
@ComponentScan(basePackages = {"com.zhejianglab.gravitationalwave.gravitationalwaveserver.service", "com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller"})
@EnableMongoRepositories(basePackages = {
    "com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.repository",
    "com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.repository",
    "com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.favorite.repository",
    "com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.repository"
})
@EnableElasticsearchRepositories(basePackages = "com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.repository")
public class Application {

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

}
