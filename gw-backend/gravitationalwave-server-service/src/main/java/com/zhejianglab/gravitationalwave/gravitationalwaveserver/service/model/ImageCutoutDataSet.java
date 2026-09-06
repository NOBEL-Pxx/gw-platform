package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;

import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

@Component
public class ImageCutoutDataSet extends DataSet {
    private static final Logger logger = LoggerFactory.getLogger(ImageCutoutDataSet.class);
    private String token = "";

    @Value("${imagecutout.username}")
    private String username;

    @Value("${imagecutout.password}")
    private String password;

    // Not used, but required by abstract base class
    @Override
    public void auth(String username, String password) {
        // No-op
    }

    @Override
    public void auth(String token) {
        // Not used. Authentication is handled by auth() with properties.
    }
    // Authenticate using credentials from application.properties
    public void auth() {
        String apiBaseUrl = "https://hips.china-vo.org";
        String loginUrl = apiBaseUrl + "/generate/login";
        RestTemplate restTemplate = new RestTemplate();
        ObjectMapper mapper = new ObjectMapper();
        try {
            Map<String, String> loginData = new HashMap<>();
            loginData.put("username", username);
            loginData.put("password", password);
            HttpHeaders headers = new HttpHeaders();
            headers.set("Content-Type", "application/json");
            HttpEntity<String> entity = new HttpEntity<>(mapper.writeValueAsString(loginData), headers);
            ResponseEntity<String> response = restTemplate.postForEntity(loginUrl, entity, String.class);
            if (response.getStatusCodeValue() == 200) {
                JsonNode json = mapper.readTree(response.getBody());
                this.token = json.path("token").asText();
                logger.info("Login successful, token obtained");
            } else {
                logger.error("Login failed: HTTP {}", response.getStatusCodeValue());
                this.token = "";
            }
        } catch (Exception e) {
            logger.error("Failed to authenticate with username/password", e);
            this.token = "";
        }
    }

    @Override
    public void download(String output, String datatype, Metadata metadata) throws IOException {
        if (metadata.getDataset_name() == null || metadata.getDataset_name().isEmpty()) {
            throw new IllegalArgumentException("Dataset name is required");
        }
        Map<String, Object> metadataMap = metadata.toMap();
        logger.info("Metadata: {}", metadataMap);

        String baseUrl = "https://hips.china-vo.org/generate";
        UriComponentsBuilder builder = UriComponentsBuilder.fromHttpUrl(baseUrl)
                .queryParam("dataset_name", metadata.getDataset_name())
                .queryParam("format", datatype)
                .queryParam("ra", metadata.getRa())
                .queryParam("dec", metadata.getDec())
                .queryParam("fov", metadata.getFov())
                .queryParam("width", metadata.getWidth())
                .queryParam("height", metadata.getHeight());

        String url = builder.toUriString();
        logger.info("Request URL: {}", url);

        RestTemplate restTemplate = new RestTemplate();
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Bearer " + this.token);
        headers.set("User-Agent", "Java-Spring RestClient");
        HttpEntity<String> entity = new HttpEntity<>(headers);

        try {
            ResponseEntity<String> response = restTemplate.exchange(
                    url,
                    HttpMethod.GET,
                    entity,
                    String.class
            );
            if (response.getStatusCodeValue() != 200) {
                logger.error("Failed to generate image: HTTP Status {}", response.getStatusCodeValue());
                throw new IOException("Failed to generate image: " + response.getStatusCodeValue());
            }
            ObjectMapper objectMapper = new ObjectMapper();
            JsonNode jsonResponse = objectMapper.readTree(response.getBody());
            String imagePath = jsonResponse.path("image_path").asText();
            if (imagePath.isEmpty()) {
                logger.error("Failed to retrieve image path from response.");
                throw new IOException("Failed to retrieve image path from response.");
            }
            String locationHeader = response.getHeaders().getLocation() != null ? response.getHeaders().getLocation().toString() : null;
            if (locationHeader != null) {
                logger.info("Redirected to: {}", locationHeader);
                imagePath = locationHeader;
            }
            ResponseEntity<byte[]> imageResponse = restTemplate.exchange(
                    imagePath,
                    HttpMethod.GET,
                    entity,
                    byte[].class
            );
            if (imageResponse.getStatusCodeValue() != 200) {
                String errorMessage = new String(imageResponse.getBody(), StandardCharsets.UTF_8);
                logger.error("Failed to download image/fits: {} - {}", imageResponse.getStatusCodeValue(), errorMessage);
                throw new IOException("Failed to download image/fits: " + errorMessage);
            }
            byte[] imageContent = imageResponse.getBody();
            if (imageContent == null || imageContent.length == 0) {
                throw new IOException("Failed to download image/fits content. The response body is empty.");
            }
            try (FileOutputStream fos = new FileOutputStream(output)) {
                fos.write(imageContent);
                logger.info("Downloaded image/fits size: {} bytes", imageContent.length);
            }
        } catch (HttpClientErrorException | HttpServerErrorException e) {
            logger.error("HTTP error during image/fits download: {} - {}", e.getStatusCode(), e.getResponseBodyAsString());
            throw new IOException("HTTP error during image/fits download: " + e.getMessage(), e);
        } catch (Exception e) {
            logger.error("Error during image/fits download", e);
            throw new IOException("Error during image/fits download: " + e.getMessage(), e);
        }
    }

    @Override
    public boolean authorized() {
        return !token.isEmpty();
    }

    @Override
    public String[] getDatatypes() {
        return new String[]{"PNG", "FITS"};
    }

    public String[] getDatasets() {
        String url = "https://hips.china-vo.org/generate/list-dataset";
        RestTemplate restTemplate = new RestTemplate();
        return restTemplate.getForObject(url, String[].class);
    }
}