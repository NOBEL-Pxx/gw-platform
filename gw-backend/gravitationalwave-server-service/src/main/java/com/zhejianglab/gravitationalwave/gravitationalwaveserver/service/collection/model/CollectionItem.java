package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.model;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.CompoundIndex;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;
import java.util.Date;

@Document(collection = "collection_items")
@CompoundIndex(name = "uk_collection_grawave", def = "{'collectionId': 1, 'grawaveId': 1}", unique = true)
public class CollectionItem {
    @Id
    private String id;
    @Indexed
    private String collectionId;
    @Indexed
    private String grawaveId;
    private String band;
    private Double ra;
    private Double dec;
    private String telescope;
    private Date addedAt;

    public CollectionItem() {}
    public CollectionItem(String collectionId, String grawaveId, String band, Double ra, Double dec, String telescope) {
        this.collectionId = collectionId;
        this.grawaveId = grawaveId;
        this.band = band;
        this.ra = ra;
        this.dec = dec;
        this.telescope = telescope;
        this.addedAt = new Date();
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getCollectionId() { return collectionId; }
    public void setCollectionId(String cid) { this.collectionId = cid; }
    public String getGrawaveId() { return grawaveId; }
    public void setGrawaveId(String gid) { this.grawaveId = gid; }
    public String getBand() { return band; }
    public void setBand(String b) { this.band = b; }
    public Double getRa() { return ra; }
    public void setRa(Double r) { this.ra = r; }
    public Double getDec() { return dec; }
    public void setDec(Double d) { this.dec = d; }
    public String getTelescope() { return telescope; }
    public void setTelescope(String t) { this.telescope = t; }
    public Date getAddedAt() { return addedAt; }
    public void setAddedAt(Date d) { this.addedAt = d; }
}
