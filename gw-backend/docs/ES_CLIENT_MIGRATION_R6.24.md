# ES Client Migration Plan (R6.24)

## Why

The gw-backend currently has two Elasticsearch clients coexisting:

| Client | Version | Used By |
|--------|---------|---------|
| `ElasticsearchClient` | 8.15.0 | Most services (lambda DSL via `co.elastic.clients.elasticsearch._types.query_dsl.Query`) |
| `RestHighLevelClient` | 7.17.28 | **Only** `ErrorDetailServiceImpl` (legacy `BoolQueryBuilder` DSL) |

This dual-client setup:

1. **Doubles the dependency footprint** (~5 MB of `elasticsearch-rest-high-level-client` jar + transitive deps, plus the risk of `ClassNotFoundException` when one is shaded and the other is not).
2. **Forces two connection pools** to the same cluster, each with its own timeouts and circuit-breaker state.
3. **Splits the team's mental model**: every code-review must ask "is this the 7.x API or the 8.x API?".
4. **Risks silent fallthrough**: `RestHighLevelClient` is in maintenance mode (Elastic announced end-of-life); security patches will eventually stop.

## Current State

`ErrorDetailServiceImpl.java` has a misleading comment:

```java
// 3. Execute ES 8.x query -- unified client (migrated from RestHighLevelClient)
```

But the import block still contains:

```java
import org.elasticsearch.client.RestHighLevelClient;
import org.elasticsearch.index.query.BoolQueryBuilder;
import org.elasticsearch.index.query.QueryBuilders;
import org.elasticsearch.search.builder.SearchSourceBuilder;
```

And the query construction uses 7.x DSL:

```java
BoolQueryBuilder boolQuery = QueryBuilders.boolQuery()
    .must(QueryBuilders.termQuery("errorCode", errorCode))
    .filter(QueryBuilders.rangeQuery("timestamp").gte(from).lte(to));
SearchSourceBuilder source = new SearchSourceBuilder().query(boolQuery);
restHighLevelClient.search(searchRequest, source, RequestOptions.DEFAULT);
```

So the migration is **partially done** -- the comment is aspirational; the code is not.

## Target State

One `ElasticsearchClient` bean, autowired everywhere. `RestHighLevelClient` deleted from both `pom.xml` files. `BoolQueryBuilder` replaced with `co.elastic.clients.elasticsearch._types.query_dsl.Query.Builder`.

## Migration Steps (3 PRs)

### PR 1: Update `ErrorDetailServiceImpl.java` to 8.x DSL

In [`ErrorDetailServiceImpl.java`](../../gravitationalwave-server-service/src/main/java/com/zhejianglab/gravitationalwave/gravitationalwaveserver/service/service/ErrorDetailServiceImpl.java):

- Replace import block:
  ```java
  // remove
  import org.elasticsearch.client.RestHighLevelClient;
  import org.elasticsearch.index.query.BoolQueryBuilder;
  import org.elasticsearch.index.query.QueryBuilders;
  import org.elasticsearch.search.builder.SearchSourceBuilder;

  // add
  import co.elastic.clients.elasticsearch._types.query_dsl.Query;
  import co.elastic.clients.elasticsearch.core.SearchRequest;
  ```

- Inject `ElasticsearchClient` (8.x) instead of `RestHighLevelClient`.

- Rewrite query construction:
  ```java
  Query q = Query.of(qb -> qb.bool(b -> b
      .must(m -> m.term(t -> t.field("errorCode").value(errorCode)))
      .filter(f -> f.range(r -> r.field("timestamp").gte(JsonData.of(from)).lte(JsonData.of(to))))
  ));

  SearchRequest req = SearchRequest.of(s -> s
      .index("error-details")
      .query(q)
      .size(50));

  SearchResponse<ErrorDetailDoc> resp = elasticsearchClient.search(req, ErrorDetailDoc.class);
  ```

- Update result type extraction (8.x returns `SearchResponse<T>`, not `SearchHits`).

- Run the ErrorDetailService unit tests; manually hit `/api/error-details?code=...` and confirm response shape unchanged.

### PR 2: Delete `RestHighLevelClient` from pom files

[`gravitationalwave-server-service/pom.xml`](../../gravitationalwave-server-service/pom.xml) and [`pom.xml`](../../pom.xml):

```xml
<!-- DELETE this block -->
<dependency>
    <groupId>org.elasticsearch.client</groupId>
    <artifactId>elasticsearch-rest-high-level-client</artifactId>
    <version>7.17.28</version>
</dependency>
```

And any transitive `elasticsearch` (7.x) dependency that was pulled in by the HL client but is no longer needed.

### PR 3: Delete `RestHighLevelClient` bean in `ElasticsearchConfig.java`

[`ElasticsearchConfig.java`](../../gravitationalwave-server-service/src/main/java/com/zhejianglab/gravitationalwave/gravitationalwaveserver/service/config/ElasticsearchConfig.java):

- Remove the `@Bean RestHighLevelClient` method.
- Remove any `@PreDestroy` shutdown hook for it.
- Keep the `ElasticsearchClient` bean (8.x) -- this is the surviving client.

## Verification Checklist

- [ ] `grep -r RestHighLevelClient gw-backend/` returns zero matches.
- [ ] `grep -r BoolQueryBuilder gw-backend/` returns zero matches.
- [ ] `mvn -pl gw-backend/gravitationalwave-server-service dependency:tree | grep elasticsearch` shows only `co.elastic.clients:elasticsearch-java:8.x.x`.
- [ ] Integration test: query an ErrorDetail doc by code + timestamp range, confirm response JSON shape matches pre-migration.
- [ ] Boot gw-backend; curl `/api/error-details?code=...`; confirm 200 OK with expected payload.
- [ ] No `ClassNotFoundException` or `NoSuchMethodError` in startup or runtime logs.

## Effort Estimate

| PR | Touched Files | Estimated Review | Risk |
|----|---------------|------------------|------|
| 1  | 1             | 45 min           | Medium (DSL rewrite, but isolated to ErrorDetail) |
| 2  | 2             | 15 min           | Low (delete only) |
| 3  | 1             | 15 min           | Low (delete only) |

Total: ~1.5 hours over 3 PRs.

## Why Not One Big PR

- Reviewability: smaller PRs get more careful review.
- Rollback: if PR 1 fails in production, PRs 2+ are independent and can ship later.
- Testing isolation: PR 1 can be tested end-to-end before the dependency is deleted.

## Why Not Just Suppress the Warning

The 7.x client works fine today. But:

- `RestHighLevelClient` is in maintenance mode; no new features, security-only patches.
- Dual clients double the connection-pool resource usage against the same ES cluster.
- New developers will copy-paste the 7.x DSL into new services, perpetuating the problem.
- SonarQube / OWASP dependency-check flags 7.17.28 as "outdated" with no upgrade path.

The cost of fixing it is small (~1.5 hours); the cost of leaving it grows linearly with new services.

## Out of Scope (R6.24 won't address)

- Migrating to the **new** Elasticsearch Java API Client (`co.elastic.clients`) -- ErrorDetailServiceImpl IS the migration target.
- Upgrading ES cluster from 7.x to 8.x (separate ops task).
- Migrating Mongo / Redis / PostgreSQL clients (no such dual-client problem there).

## Deployment

- Same CI/CD pipeline as R6.22: `python scripts/ci/version.py tag` -> `bash scripts/ci/deploy.sh` -> `python scripts/sync-to-zjlab.py backend`.
- Rollback: previous tag's image is preserved in `localhost:8093/gw-backend:<old-tag>`; `docker compose up -d --force-recreate --no-deps gw-backend` reverts.
