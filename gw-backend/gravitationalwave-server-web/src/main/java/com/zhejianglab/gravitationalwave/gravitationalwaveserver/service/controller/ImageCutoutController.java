package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ImageCutoutDataSet;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.Metadata;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.*;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

@Component
@RestController
@RequestMapping("/api/app/gravitationalwave/image-cutout")
public class ImageCutoutController {

    private static final Logger log = LoggerFactory.getLogger(ImageCutoutController.class);

    @Autowired
    private ImageCutoutDataSet dataSet;

    /**
     * R6.85-A-V1MARKER: emit a recognizable startup log line so {@code build-and-deploy-jar.py}'s
     * {@code check_marker_log} AND-check can confirm the bean lifecycle completed for this
     * controller. See [[r685-summary]] for the R6.85 iron-rule convention.
     */
    @PostConstruct
    public void init() {
        log.info("R6.88: ImageCutoutController initialized");
    }

    /**
     * R6.85-A-PREDESTROY: log shutdown so a container restart leaves a visible lifecycle trace.
     * ImageCutoutController owns no RestTemplate/ExecutorService, so nothing to close; this is
     * symmetry with R6.85b (LlmController + PipelineProxyController) for the post-deploy marker
     * scanner.
     */
    @PreDestroy
    public void shutdown() {
        log.info("R6.88: ImageCutoutController shutting down");
    }

    @PostMapping("/auth")
    public ResponseEntity<String> auth() {
        // R6.85-A-NULLGUARD: surface 503 rather than NPE if @Autowired failed.
        if (dataSet == null) {
            log.error("ImageCutoutDataSet not initialized — please retry in a moment");
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body("Image cutout service not initialized — please retry in a moment");
        }
        dataSet.auth();
        return ResponseEntity.ok("Authenticated successfully");
    }

    @GetMapping("/datasets")
    public ResponseEntity<List<String>> getDatasets() {
        // R6.85-A-NULLGUARD: surface 503 rather than NPE if @Autowired failed.
        if (dataSet == null) {
            log.error("ImageCutoutDataSet not initialized — please retry in a moment");
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).build();
        }
        String[] datasets = dataSet.getDatasets();
        return ResponseEntity.ok(Arrays.asList(datasets));
    }

    @PostMapping("/download")
    public ResponseEntity<String> downloadImage(@RequestParam String output,
                                                @RequestParam String datatype,
                                                @RequestBody Metadata metadata) {
        // R6.85-A-NULLGUARD: surface 503 rather than NPE if @Autowired failed.
        if (dataSet == null) {
            log.error("ImageCutoutDataSet not initialized — please retry in a moment");
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body("Image cutout service not initialized — please retry in a moment");
        }
        try {
            dataSet.download(output, datatype, metadata);
            if ("PNG".equalsIgnoreCase(datatype)) {
                return ResponseEntity.ok("Image/fits: image downloaded successfully");
            } else if ("png".equalsIgnoreCase(datatype)) {
                return ResponseEntity.ok("Image/fits: image downloaded successfully");
            } else if  ("FITS".equalsIgnoreCase(datatype)){
                return ResponseEntity.ok("Image/fits: fits downloaded successfully");
            } else if  ("fits".equalsIgnoreCase(datatype)){
                return ResponseEntity.ok("Image/fits: fits downloaded successfully");
            }
            // R6.88: datatype was neither PNG nor FITS — surface 400 instead of returning null
            // (the previous behaviour silently produced an NPE for the caller).
            log.warn("downloadImage: unsupported datatype={}", datatype);
            // R6.88 security hardening (W1 from 3-perspective review): sanitize the echoed datatype
            // to strip control chars + HTML-significant chars so the message cannot be abused for
            // XSS (frontend `dangerouslySetInnerHTML`), CSV-formula injection, or CRLF/response
            // splitting. Whitelist-friendly: anything outside [A-Za-z0-9_ -] becomes '?'.
            String safeDatatype = datatype.replaceAll("[^A-Za-z0-9_\\- ]", "?");
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .body("Invalid datatype: '" + safeDatatype + "'. Supported values: PNG, FITS.");
        } catch (IOException e) {
            // R6.89 W3: do NOT echo e.getMessage() to the caller — it can leak internal file
            // paths (e.g., /tmp/cutout-2026-09-12-XYZ.tmp), Mongo ObjectIds, or other host-
            // specific details. Log the full exception server-side; return a generic message.
            log.error("downloadImage failed (datatype={}, output={}): {}",
                    datatype, output, e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body("Failed to download image. Please retry; if it persists, contact support.");
        }
    }
}