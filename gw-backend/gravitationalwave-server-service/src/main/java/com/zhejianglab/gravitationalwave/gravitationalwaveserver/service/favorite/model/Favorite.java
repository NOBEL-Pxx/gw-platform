package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.favorite.model;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.CompoundIndex;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;
import java.util.Date;

@Document(collection = "favorites")
@CompoundIndex(name = "uk_user_grawave", def = "{'userId': 1, 'grawaveId': 1}", unique = true)
public class Favorite {
    @Id
    private String id;
    @Indexed
    private String userId;
    @Indexed
    private String grawaveId;
    private String band;
    private Double ra;
    private Double dec;
    private String telescope;
    private Date createdAt;

    public Favorite() {}
    public Favorite(String userId, String grawaveId, String band, Double ra, Double dec, String telescope) {
        this.userId = userId;
        this.grawaveId = grawaveId;
        this.band = band;
        this.ra = ra;
        this.dec = dec;
        this.telescope = telescope;
        this.createdAt = new Date();
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    public String getGrawaveId() { return grawaveId; }
    public void setGrawaveId(String grawaveId) { this.grawaveId = grawaveId; }
    public String getBand() { return band; }
    public void setBand(String band) { this.band = band; }
    public Double getRa() { return ra; }
    public void setRa(Double ra) { this.ra = ra; }
    public Double getDec() { return dec; }
    public void setDec(Double dec) { this.dec = dec; }
    public String getTelescope() { return telescope; }
    public void setTelescope(String telescope) { this.telescope = telescope; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
}
