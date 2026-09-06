package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.repository;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.model.Collection;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import java.util.List;
import java.util.Optional;

public interface CollectionRepository extends MongoRepository<Collection, String> {
    Page<Collection> findByOwnerId(String ownerId, Pageable pageable);
    List<Collection> findByOwnerId(String ownerId);
    Page<Collection> findByIsPublicTrue(Pageable pageable);
    Optional<Collection> findByShareToken(String shareToken);
}
