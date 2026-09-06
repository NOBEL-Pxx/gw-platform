package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.model;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;
import java.util.Date;

@Document(collection = "collections")
public class Collection {
    @Id
    private String id;
    @Indexed
    private String ownerId;
    private String name;
    private String description;
    private boolean isPublic;
    private String shareToken;  // null or UUID for sharing
    private Date createdAt;
    private Date updatedAt;

    public Collection() {}
    public Collection(String ownerId, String name, String description) {
        this.ownerId = ownerId;
        this.name = name;
        this.description = description;
        this.isPublic = false;
        this.createdAt = new Date();
        this.updatedAt = new Date();
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getOwnerId() { return ownerId; }
    public void setOwnerId(String ownerId) { this.ownerId = ownerId; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getDescription() { return description; }
    public void setDescription(String desc) { this.description = desc; }
    public boolean isPublic() { return isPublic; }
    public void setPublic(boolean isPublic) { this.isPublic = isPublic; }
    public String getShareToken() { return shareToken; }
    public void setShareToken(String token) { this.shareToken = token; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date d) { this.createdAt = d; }
    public Date getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Date d) { this.updatedAt = d; }
}
