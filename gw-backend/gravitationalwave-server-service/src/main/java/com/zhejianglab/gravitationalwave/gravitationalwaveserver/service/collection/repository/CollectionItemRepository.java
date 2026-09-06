package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.repository;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.model.CollectionItem;
import org.springframework.data.mongodb.repository.MongoRepository;
import java.util.List;

public interface CollectionItemRepository extends MongoRepository<CollectionItem, String> {
    List<CollectionItem> findByCollectionId(String collectionId);
    void deleteByCollectionIdAndGrawaveId(String collectionId, String grawaveId);
    void deleteAllByCollectionId(String collectionId);
    long countByCollectionId(String collectionId);
}
