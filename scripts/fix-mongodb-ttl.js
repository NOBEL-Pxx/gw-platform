// ═══════════════════════════════════════════════════════════════════════════
// GravitationalWave Platform — MongoDB TTL & Cleanup Indexes (v4.16)
// ═══════════════════════════════════════════════════════════════════════════
// Run: docker exec -i gw-mongodb mongosh -u admin -p "$MONGO_ROOT_PASSWORD" \
//        --authenticationDatabase admin < fix-mongodb-ttl.js
// ═══════════════════════════════════════════════════════════════════════════

db = db.getSiblingDB('gravitationalwave');

print('=== MongoDB TTL & Cleanup Index Setup (v4.16) ===');
print('');

// ── 1. Comments: TTL 730 days (2 years) on createdAt ──────────────────────
// After 730 days, old comments are auto-deleted by MongoDB's TTL reaper.
// This prevents the comments collection from growing unboundedly.
try {
    db.comments.dropIndex('createdAt_1');
} catch(e) { /* may not exist */ }
db.comments.createIndex(
    { "createdAt": 1 },
    { expireAfterSeconds: 730 * 24 * 3600, name: "ttl_comments_730d" }
);
print('✓ Comments TTL index: 730 days (auto-delete after 2 years)');

// ── 2. Favorites: TTL 365 days (1 year) on createdAt ──────────────────────
// Favorites are transient research interests — if not accessed for 1 year,
// they are likely stale. Users can re-favorite if needed.
try {
    db.favorites.dropIndex('createdAt_1');
} catch(e) { /* may not exist */ }
db.favorites.createIndex(
    { "createdAt": 1 },
    { expireAfterSeconds: 365 * 24 * 3600, name: "ttl_favorites_365d" }
);
print('✓ Favorites TTL index: 365 days (auto-delete after 1 year)');

// ── 3. Collections & CollectionItems: 730 days (2 years) ───────────────────
// Collections represent research groupings. Longer TTL than favorites.
try {
    db.collections.dropIndex('createdAt_1');
} catch(e) { /* may not exist */ }
db.collections.createIndex(
    { "createdAt": 1 },
    { expireAfterSeconds: 730 * 24 * 3600, name: "ttl_collections_730d" }
);
print('✓ Collections TTL index: 730 days');

try {
    db.collectionItems.dropIndex('createdAt_1');
} catch(e) { /* may not exist */ }
db.collectionItems.createIndex(
    { "createdAt": 1 },
    { expireAfterSeconds: 730 * 24 * 3600, name: "ttl_collection_items_730d" }
);
print('✓ CollectionItems TTL index: 730 days');

// ── 4. Users: No TTL — user accounts never auto-expire ────────────────────
print('✓ Users: no TTL (accounts persist indefinitely)');

// ── 5. Audit logs: TTL 90 days (moved to separate collection later) ───────
// Pre-create the audit_logs collection with TTL if it doesn't exist yet.
// This is forward-looking for the audit log feature (architecture-roadmap §6).
try {
    db.audit_logs.createIndex(
        { "timestamp": 1 },
        { expireAfterSeconds: 90 * 24 * 3600, name: "ttl_audit_logs_90d" }
    );
    print('✓ Audit logs TTL index: 90 days (forward-looking)');
} catch(e) {
    print('⚠ Audit logs collection not yet created — index will apply on first insert');
}

// ── 6. Verify all indexes ─────────────────────────────────────────────────
print('');
print('=== Current Indexes ===');
db.getCollectionNames().forEach(function(coll) {
    print('\n--- ' + coll + ' ---');
    db[coll].getIndexes().forEach(function(idx) {
        var ttl = idx.expireAfterSeconds || 'none';
        print('  ' + idx.name + ' (TTL: ' + ttl + ')');
    });
});

print('');
print('=== Done. TTL cleanup schedule ===');
print('  Comments:         730 days (2 years)');
print('  Favorites:        365 days (1 year)');
print('  Collections:      730 days (2 years)');
print('  CollectionItems:  730 days (2 years)');
print('  Audit logs:       90 days');
print('  Users:            NEVER (persistent)');
