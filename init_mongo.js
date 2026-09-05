// ── Create application-level user (v4.12: least-privilege hardening) ──
// Root admin (MONGO_INITDB_ROOT_USERNAME) is reserved for administration only.
// gw-app has readWrite on gravitationalwave DB — no admin.* or cluster admin rights.
db = db.getSiblingDB('admin');
const appUser = process.env.MONGO_APP_USER || 'gw-app';
const appPassword = process.env.MONGO_APP_PASSWORD;
if (appPassword && appPassword.length >= 12) {
    // Drop if re-initialising (idempotent)
    try { db.dropUser(appUser); } catch (e) { /* not found */ }
    db.createUser({
        user: appUser,
        pwd: appPassword,
        roles: [{ role: 'readWrite', db: 'gravitationalwave' }]
    });
    print(`Application user '${appUser}' created on gravitationalwave (readWrite)`);
} else {
    print('WARNING: MONGO_APP_PASSWORD not set or too short (<12 chars) — skipping app user creation');
}

// ── v4.16: Production mode guard — skip seed data in production ──
// Set environment variable SKIP_SEED_DATA=true in production docker-compose.yml
// or docker-compose.prod.yml to prevent demo data insertion.
const skipSeed = (process.env.SKIP_SEED_DATA || 'false').toLowerCase() === 'true';

// ── Demo seed data (DEVELOPMENT ONLY) ──
db = db.getSiblingDB('gravitationalwave');

if (!skipSeed) {

db.comments.insertMany([
  {
    grawaveId: "demo-obs-001",
    content: "WISE W1 band SNR high, suspected variable source",
    userId: "researcher-01",
    category: "analysis",
    createdAt: new Date("2026-06-15T08:30:00Z")
  },
  {
    grawaveId: "demo-obs-001",
    content: "Cross-matched with ZTF alert stream — no counterpart found",
    userId: "researcher-02",
    category: "crossmatch",
    createdAt: new Date("2026-06-15T10:15:00Z")
  },
  {
    grawaveId: "demo-obs-003",
    content: "Possible M33 globular cluster contamination",
    userId: "researcher-01",
    category: "analysis",
    createdAt: new Date("2026-06-16T14:00:00Z")
  },
  {
    grawaveId: "demo-obs-005",
    content: "Follow-up observation recommended — unusual light curve",
    userId: "researcher-03",
    category: "recommendation",
    createdAt: new Date("2026-06-17T09:45:00Z")
  },
  {
    grawaveId: "demo-obs-002",
    content: "Astrometry offset within 0.5 arcsec — likely real source",
    userId: "researcher-02",
    category: "verification",
    createdAt: new Date("2026-06-18T11:00:00Z")
  }
]);

print("Demo data inserted into gravitationalwave.comments");

} else {
    print("SKIP_SEED_DATA=true — demo data NOT inserted (production mode)");
}

// ── TTL Indexes (v4.16): auto-expire old data to prevent unbounded growth ──
// MongoDB TTL reaper runs every 60s and deletes documents where indexed date
// field is older than (now - expireAfterSeconds).

// Comments: 730 days (2 years) — research discussions have long-term value
db.comments.createIndex(
    { "createdAt": 1 },
    { expireAfterSeconds: 730 * 24 * 3600, name: "ttl_comments_730d" }
);
print("TTL index: comments.createdAt → 730 days");

// Favorites: 365 days (1 year) — transient research interest
db.favorites.createIndex(
    { "createdAt": 1 },
    { expireAfterSeconds: 365 * 24 * 3600, name: "ttl_favorites_365d" }
);
print("TTL index: favorites.createdAt → 365 days");

// Collections: 730 days (2 years)
db.collections.createIndex(
    { "createdAt": 1 },
    { expireAfterSeconds: 730 * 24 * 3600, name: "ttl_collections_730d" }
);
print("TTL index: collections.createdAt → 730 days");

// CollectionItems: 730 days (2 years)
db.collectionItems.createIndex(
    { "createdAt": 1 },
    { expireAfterSeconds: 730 * 24 * 3600, name: "ttl_collection_items_730d" }
);
print("TTL index: collectionItems.createdAt → 730 days");

// Audit logs: 90 days (forward-looking for audit logging feature)
try {
    db.audit_logs.createIndex(
        { "timestamp": 1 },
        { expireAfterSeconds: 90 * 24 * 3600, name: "ttl_audit_logs_90d" }
    );
    print("TTL index: audit_logs.timestamp → 90 days");
} catch (e) {
    print("Note: audit_logs collection not yet created (index will apply on first insert)");
}
