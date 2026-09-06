package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;

import lombok.Data;
import java.io.Serializable;

@Data
public class ErrorDetailResponseDTO implements Serializable {
    private String id;
    private String uuid;
    private String fits_path;
    private String img_path;
    private String anomaly_log_path;
    private String anomaly_type;
    private Double fov;
    private Double ra;
    private Double dec;
    private Integer width;
    private Integer height;
    private String start_date;
    private String end_date;
}