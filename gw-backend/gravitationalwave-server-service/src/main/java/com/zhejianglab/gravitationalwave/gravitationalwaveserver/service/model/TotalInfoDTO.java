package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;
import lombok.AllArgsConstructor;
import lombok.Data;

import java.io.Serializable;
@Data
@AllArgsConstructor(staticName = "of")
public class TotalInfoDTO {
    private int page;
    private int page_size;
    private long total_count;
}
