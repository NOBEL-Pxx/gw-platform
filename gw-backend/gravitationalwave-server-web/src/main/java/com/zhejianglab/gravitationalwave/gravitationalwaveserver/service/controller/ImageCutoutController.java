package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ImageCutoutDataSet;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.Metadata;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

@Component
@RestController
@RequestMapping("/api/app/gravitationalwave/image-cutout")
public class ImageCutoutController {

    @Autowired
    private ImageCutoutDataSet dataSet;

    @PostMapping("/auth")
    public ResponseEntity<String> auth() {
        dataSet.auth();
        return ResponseEntity.ok("Authenticated successfully");
    }

    @GetMapping("/datasets")
    public ResponseEntity<List<String>> getDatasets() {
        String[] datasets = dataSet.getDatasets();
        return ResponseEntity.ok(Arrays.asList(datasets));
    }

    @PostMapping("/download")
    public ResponseEntity<String> downloadImage(@RequestParam String output,
                                                @RequestParam String datatype,
                                                @RequestBody Metadata metadata) {
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
        } catch (IOException e) {
            return ResponseEntity.status(500).body("Failed to download image: " + e.getMessage());
        }
        return null;
    }
}