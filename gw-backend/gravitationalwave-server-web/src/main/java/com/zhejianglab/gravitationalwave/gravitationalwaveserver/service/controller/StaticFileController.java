package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.InputStreamResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

@RestController
@Slf4j
@RequestMapping("/static-files")
public class StaticFileController {

    private static final String BASE_DIRECTORY = "/app/Ali_PW";
    private static final String FITS_PATH_PREFIX = "fitsfile/";
    private static final String IMAGE_PATH_PREFIX = "imagefile/";

    @Data
    @AllArgsConstructor
    private static class FileRequest {
        private String baseDir;
        private String relativePath;
    }

    @CrossOrigin(origins = "*")
    @GetMapping("/fits/**")
    public ResponseEntity<InputStreamResource> downloadFits(HttpServletRequest request) throws IOException {
        String requestUri = request.getRequestURI();
        String fitsPath = requestUri.replace("/static-files/fits/", "");

        log.info(fitsPath);
        if (fitsPath == null || fitsPath.isEmpty()) {
            log.error("FITS文件路径参数为空");
            return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
        }
        String fullRelativePath = FITS_PATH_PREFIX + fitsPath;
        log.info(fullRelativePath);

        return downloadFile(new FileRequest(BASE_DIRECTORY, fullRelativePath));
    }

    @CrossOrigin(origins = "*")
    @GetMapping("/image/**")
    public ResponseEntity<InputStreamResource> downloadImage(HttpServletRequest request) throws IOException {
        String requestUri = request.getRequestURI();
        String imagePath = requestUri.replace("/static-files/image/", "");

        log.info(imagePath);
        if (imagePath == null || imagePath.isEmpty()) {
            log.error("FITS文件路径参数为空");
            return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
        }
        String fullRelativePath = IMAGE_PATH_PREFIX + imagePath;
        log.info(fullRelativePath);

        return downloadFile(new FileRequest(BASE_DIRECTORY, fullRelativePath));
    }

    private ResponseEntity<InputStreamResource> downloadFile(FileRequest fileRequest) throws IOException {
        String baseDir = fileRequest.getBaseDir();
        String relativePath = fileRequest.getRelativePath();

        try {

            Path basePath = Paths.get(baseDir).normalize();
            Path resolvedPath = basePath.resolve(relativePath).normalize();
            log.info(resolvedPath.toString());

            if (!resolvedPath.startsWith(basePath)) {
                log.warn(resolvedPath.toString());
                return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
            }

            if (!Files.exists(resolvedPath)) {
                log.error(resolvedPath.toString());
                return ResponseEntity.status(HttpStatus.NOT_FOUND).build();
            }
            if (!Files.isRegularFile(resolvedPath)) {
                log.error(resolvedPath.toString());
                return ResponseEntity.status(HttpStatus.BAD_REQUEST).build();
            }
            if (!Files.isReadable(resolvedPath)) {
                log.error(resolvedPath.toString());
                return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
            }

            InputStreamResource resource = new InputStreamResource(Files.newInputStream(resolvedPath));
            String mediaType = getMediaTypeForFileName(resolvedPath.getFileName().toString());

            HttpHeaders headers = new HttpHeaders();
            headers.add(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + resolvedPath.getFileName() + "\"");
            headers.add(HttpHeaders.CONTENT_TYPE, mediaType);

            return ResponseEntity.ok()
                    .headers(headers)
                    .contentLength(Files.size(resolvedPath))
                    .contentType(MediaType.parseMediaType(mediaType))
                    .body(resource);

        } catch (Exception e) {
            log.error("下载失败", e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).build();
        }
    }

    private String getMediaTypeForFileName(String fileName) {
        String fileExtension = getFileExtension(fileName).toLowerCase();
        switch (fileExtension) {
            case "jpg":
            case "jpeg":
                return "image/jpeg";
            case "png":
                return "image/png";
            case "fits":
            case "fit":
                return "application/fits";
            default:
                return "application/octet-stream";
        }
    }

    private String getFileExtension(String fileName) {
        if (fileName == null || fileName.isEmpty()) {
            return "";
        }
        int dotIndex = fileName.lastIndexOf(".");
        return (dotIndex != -1) ? fileName.substring(dotIndex + 1) : "";
    }

    @GetMapping("/test-route")
    public ResponseEntity<String> testRoute() {
        log.info("测试接口被调用");
        return ResponseEntity.ok("路由测试成功");
    }
}