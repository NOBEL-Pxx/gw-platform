package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;

import lombok.Data;
import lombok.experimental.Accessors;
import org.springframework.data.annotation.Id;
import org.springframework.data.elasticsearch.annotations.Document;
import org.springframework.data.elasticsearch.annotations.Field;
import org.springframework.data.elasticsearch.annotations.FieldType;
import java.io.Serializable;

@Data
@Accessors(chain = true)
@Document(indexName = "errordetail")
public class ErrorDetailDO implements Serializable {
    @Id
    private String id;

    @Field(type = FieldType.Keyword)
    private String error_id;

    @Field(type = FieldType.Text)
    private String logContent;

    @Field(type = FieldType.Keyword)
    private String uuid;

    @Field(type = FieldType.Keyword)
    private String fits_path;

    @Field(type = FieldType.Keyword)
    private String img_path;

    @Field(type = FieldType.Keyword)
    private String anomaly_log_path;

    @Field(type = FieldType.Keyword)
    private String anomaly_type;

    @Field(type = FieldType.Double)
    private Double fov;

    @Field(type = FieldType.Double)
    private Double ra;

    @Field(type = FieldType.Double)
    private Double dec;

    @Field(type = FieldType.Integer)
    private Integer width;

    @Field(type = FieldType.Integer)
    private Integer height;

    @Field(type = FieldType.Date)
    private String start_date;

    @Field(type = FieldType.Date)
    private String end_date;
}