package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import lombok.experimental.Accessors;
import org.springframework.data.annotation.Id;
import org.springframework.data.elasticsearch.annotations.Document;
import org.springframework.data.elasticsearch.annotations.Field;
import org.springframework.data.elasticsearch.annotations.FieldType;
import org.springframework.data.elasticsearch.annotations.GeoPointField;
import org.springframework.data.elasticsearch.core.geo.GeoPoint;

import java.util.List;

@Data
@Accessors(chain = true)
@Document(indexName = "alicptabnormal")
public class GrawaveDataDO {
    @Id
    private String id;

    @Field(type = FieldType.Keyword)
    private String raw_id;

    @Field(type = FieldType.Keyword)
    private String fits_path;

    @Field(type = FieldType.Keyword)
    private String img_path;

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

    @Field(type = FieldType.Keyword)
    private String band;

    @Field(type = FieldType.Keyword)
    private String telescope;

    @GeoPointField
    private GeoPoint mapping_location;

    @Field(type = FieldType.Keyword)
    private List<String> uuid;

    // v4.54-r4d: client-side hint. TRUE when the img_path points to a missing
    // or zero-coverage FITS file on disk. Populated by SearchService after
    // ES fetch (Files.exists probe against /app/Ali_PW/imagefile/...). Never
    // indexed in ES (no @Field annotation). Jackson serializes on output and
    // ignores on input — fine because ES source map has no isBlank key.
    private Boolean isBlank;
}