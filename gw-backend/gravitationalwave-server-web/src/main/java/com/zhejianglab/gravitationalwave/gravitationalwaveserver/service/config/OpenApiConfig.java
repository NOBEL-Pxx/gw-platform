package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.security.SecurityScheme;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

    @Bean
    public OpenAPI gwOpenAPI() {
        return new OpenAPI()
            .info(new Info()
                .title("GravitationalWave Backend API")
                .description("Spring Boot REST API for the GravitationalWave astronomical data platform. Provides search, authentication, comments, favorites, collections, and LLM proxy endpoints.")
                .version("v4.38")
                .contact(new Contact()
                    .name("GravitationalWave Contributors")
                    .url("https://alicpt.lhr.life")))
            .addSecurityItem(new SecurityRequirement().addList("BearerAuth"))
            .schemaRequirement("BearerAuth", new SecurityScheme()
                .type(SecurityScheme.Type.HTTP)
                .scheme("bearer")
                .bearerFormat("JWT")
                .description("Enter JWT Bearer token from /api/auth/login"));
    }
}
