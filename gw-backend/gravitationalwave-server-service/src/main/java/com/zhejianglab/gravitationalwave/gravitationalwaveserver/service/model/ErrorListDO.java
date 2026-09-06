package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;
import lombok.Data;
import java.io.Serializable;
import java.util.List;

@Data
public class ErrorListDO implements Serializable {
    private String id;
    private String error_id;
    private String telescope;
    private String band;
    private List<Double> rafield;
    private List<Double> decfield;
    private Double fov;
    private Integer width;
    private Integer height;
    private List<String> anomaly_type;
    private String start_date;
    private String end_date;
}