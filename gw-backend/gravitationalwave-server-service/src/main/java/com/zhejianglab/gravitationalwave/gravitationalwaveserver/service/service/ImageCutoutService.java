package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ImageCutoutDataSet;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.Metadata;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.util.concurrent.CompletableFuture;

/**
 * R6.90 B1: ImageCutoutService — async wrapper for the blocking
 * {@link ImageCutoutDataSet#download} call.
 *
 * <p>Why a separate service (rather than {@code @Async} on the controller method):
 * Spring's @Async relies on AOP proxying, which is BYPASSED for self-invoked
 * methods. Putting @Async on a controller method called from within the same
 * controller would silently run synchronously. The fix is to either (a) extract
 * to a separate @Service bean, or (b) inject the controller as a self-reference
 * via {@code @Lazy ApplicationContext}. (a) is cleaner for testability and
 * dependency direction.
 *
 * <p>The controller delegates here, gets a {@link CompletableFuture} back, and
 * Spring's MVC async support holds the response open until the future completes
 * (or fails). The Tomcat request thread is freed the moment the controller
 * returns the future; the actual HTTP I/O + file write happens on the
 * {@code imageCutoutExecutor} pool.
 */
@Service
public class ImageCutoutService {

    private static final Logger log = LoggerFactory.getLogger(ImageCutoutService.class);

    @Autowired
    private ImageCutoutDataSet dataSet;

    /**
     * R6.90 B1: download a cutout image/fits asynchronously.
     *
     * @param output   server-side file path to write to (e.g., /app/Ali_PW/imagefile/...)
     * @param datatype PNG or FITS
     * @param metadata cutout parameters (ra, dec, fov, dataset_name, ...)
     * @return CompletableFuture completing with success message, or failing with
     *         IOException if the upstream china-vo.org call fails.
     */
    @Async("imageCutoutExecutor")
    public CompletableFuture<String> downloadAsync(String output, String datatype, Metadata metadata) {
        log.info("B1 async download start: output={} datatype={} dataset={}",
            output, datatype, metadata.getDataset_name());
        try {
            dataSet.download(output, datatype, metadata);
            return CompletableFuture.completedFuture("Image/fits: downloaded successfully");
        } catch (IOException e) {
            log.error("B1 async download failed (output={}, datatype={}): {}",
                output, datatype, e.getMessage(), e);
            CompletableFuture<String> failed = new CompletableFuture<>();
            failed.completeExceptionally(e);
            return failed;
        }
    }
}
