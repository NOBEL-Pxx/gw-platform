package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.repository;



import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.model.Comment;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
public interface CommentRepository extends MongoRepository<Comment, String> {
    Page<Comment> findByGrawaveId(String grawaveId, Pageable pageable);
    Page<Comment> findByUserId(String userId, Pageable pageable);
    Page<Comment> findByCategory(String category, Pageable pageable);
    Page<Comment> findAll(Pageable pageable);
}

