package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ImageCutoutDataSet;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.Metadata;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.ImageCutoutService;

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
import java.util.concurrent.CompletableFuture;

@Component
@RestController
@RequestMapping("/api/app/gravitationalwave/image-cutout")
public class ImageCutoutController {

    private static final Logger log = LoggerFactory.getLogger(ImageCutoutController.class);

    @Autowired
    private ImageCutoutDataSet dataSet;

    /**
     * R6.90 B1: ImageCutoutService handles the async download path. The controller
     * delegates to it, returning a {@link CompletableFuture} so Spring's MVC async
     * support holds the response open until the future completes — but the Tomcat
     * request thread is released the moment this method returns.
     */
    @Autowired
    private ImageCutoutService imageCutoutService;

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

    /**
     * R6.90 B5: auth() is now idempotent. The ImageCutoutDataSet layer tracks the
     * current token + auth state; repeated auth() calls with a valid token skip
     * the network round-trip to china-vo.org. This is a hot-path optimization
     * for frontends that retry on transient failures.
     */
    @PostMapping("/auth")
    public ResponseEntity<String> auth() {
        if (dataSet == null) {
            log.error("ImageCutoutDataSet not initialized — please retry in a moment");
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body("Image cutout service not initialized — please retry in a moment");
        }
        boolean wasAuth = dataSet.authorized();
        dataSet.auth();
        boolean nowAuth = dataSet.authorized();
        if (wasAuth && nowAuth) {
            log.info("B5 auth() idempotent: already authenticated, skipped network call");
            return ResponseEntity.ok("Already authenticated (idempotent)");
        }
        return ResponseEntity.ok(nowAuth
            ? "Authenticated successfully"
            : "Authentication failed — check imagecutout.username/password");
    }

    @GetMapping("/datasets")
    public ResponseEntity<List<String>> getDatasets() {
        if (dataSet == null) {
            log.error("ImageCutoutDataSet not initialized — please retry in a moment");
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).build();
        }
        String[] datasets = dataSet.getDatasets();
        return ResponseEntity.ok(Arrays.asList(datasets));
    }

    /**
     * R6.90 B1: download is now async. The Tomcat request thread is freed as
     * soon as we return the {@link CompletableFuture}. The actual upstream
     * HTTP call (china-vo.org) + file write happens on the
     * {@code imageCutoutExecutor} thread pool. The response is held open by
     * Spring's MVC async support until the future completes.
     */
    @PostMapping("/download")
    public CompletableFuture<ResponseEntity<String>> downloadImage(@RequestParam String output,
                                                                   @RequestParam String datatype,
                                                                   @RequestBody Metadata metadata) {
        if (dataSet == null || imageCutoutService == null) {
            log.error("ImageCutoutService not initialized — please retry in a moment");
            return CompletableFuture.completedFuture(
                ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body("Image cutout service not initialized — please retry in a moment"));
        }

        // R6.88: datatype validation done up-front (was deferred to after download,
        // causing a wasted upstream round-trip on bad input).
        boolean pngType = "PNG".equalsIgnoreCase(datatype) || "png".equalsIgnoreCase(datatype);
        boolean fitsType = "FITS".equalsIgnoreCase(datatype) || "fits".equalsIgnoreCase(datatype);
        if (!pngType && !fitsType) {
            log.warn("downloadImage: unsupported datatype={}", datatype);
            String safeDatatype = datatype == null ? "" : datatype.replaceAll("[^A-Za-z0-9_\\- ]", "?");
            return CompletableFuture.completedFuture(
                ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .body("Invalid datatype: '" + safeDatatype + "'. Supported values: PNG, FITS."));
        }

        // Delegate to async service. .thenApply / .exceptionally wire the response.
        return imageCutoutService.downloadAsync(output, datatype, metadata)
            .<ResponseEntity<String>>thenApply(msg -> {
                if (pngType) {
                    return ResponseEntity.ok("Image/fits: image downloaded successfully");
                }
                return ResponseEntity.ok("Image/fits: fits downloaded successfully");
            })
            .exceptionally(ex -> {
                // R6.89 W3: do NOT echo ex.getMessage() to the caller — it can leak internal
                // file paths, Mongo ObjectIds, or host-specific details.
                Throwable root = ex.getCause() != null ? ex.getCause() : ex;
                log.error("downloadImage failed (datatype={}, output={}): {}",
                    datatype, output, root.getMessage(), root);
                return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body("Failed to download image. Please retry; if it persists, contact support.");
            });
    }
}
