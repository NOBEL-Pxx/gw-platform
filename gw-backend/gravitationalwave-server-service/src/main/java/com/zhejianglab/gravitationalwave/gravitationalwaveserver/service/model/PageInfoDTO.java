package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.io.Serializable;

public class PageInfoDTO {

    private int page;
    private int pageSize;

    // Constructor
    public PageInfoDTO(int page, int pageSize) {
        this.page = page;
        this.pageSize = pageSize;
    }

}
