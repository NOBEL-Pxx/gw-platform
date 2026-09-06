package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;

import lombok.Getter;
import lombok.Setter;

import java.util.HashMap;
import java.util.Map;

@Getter
@Setter
public class Metadata {
    private String dataset_name;
    private double ra;
    private double dec;
    private double fov;
    private int width;
    private int height;

    public Map<String, Object> toMap() {
        Map<String, Object> map = new HashMap<>();
        map.put("dataset_name", dataset_name);
        map.put("ra", ra);
        map.put("dec", dec);
        map.put("fov", fov);
        map.put("width", width);
        map.put("height", height);
        return map;
    }
}