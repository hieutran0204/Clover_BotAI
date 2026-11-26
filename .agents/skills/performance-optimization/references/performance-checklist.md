# Performance Checklist

Quick reference checklist for backend API performance. Use alongside the `performance-optimization` skill.

## Table of Contents

- [Backend Checklist](#backend-checklist)
- [Database Optimization](#database-optimization)
- [Caching Strategies](#caching-strategies)
- [Async and Concurrency](#async-and-concurrency)
- [Common Anti-Patterns](#common-anti-patterns)

## Backend Checklist

### API
- [ ] Response times < 200ms (p95)
- [ ] No synchronous heavy computation in request handlers
- [ ] Bulk operations instead of loops of individual calls
- [ ] Response compression (gzip/brotli via middleware)
- [ ] Appropriate caching (in-memory, Redis, CDN)
- [ ] List endpoints paginated (never `SELECT *` without LIMIT)

### Infrastructure
- [ ] CDN for static assets
- [ ] Horizontal scaling configured (if needed)
- [ ] Health check endpoint for load balancer

## Database Optimization

### Query Plans
- [ ] `EXPLAIN ANALYZE` captured **before** the fix — it is the baseline
- [ ] `Seq Scan` on a large table understood: index missing, unusable, or genuinely not worth it
- [ ] Estimated vs actual `rows=` within an order of magnitude
- [ ] No `Sort` node that a composite index could absorb
- [ ] Plan re-checked after the change — an index that did not change the plan gets reverted

### Index Strategy
- [ ] Composite index column order is equality first, then range/sort
- [ ] Index covers the query shape (filter + sort), not just one column in isolation
- [ ] Covering index considered for hot read paths
- [ ] Not indexing low-selectivity columns for the dominant value
- [ ] Expression index used where the query applies a function (`lower(email)`)
- [ ] Write cost measured on write-heavy tables (every index taxes every INSERT/UPDATE)
- [ ] Unused and duplicate indexes dropped

### Connection Pooling
- [ ] One pool per process, not per request or per module
- [ ] `instances × pool max` stays under the database's `max_connections`
- [ ] `pool_timeout` set so exhaustion fails fast instead of queueing forever
- [ ] Serverless / autoscaling fronted by a multiplexing proxy (pgbouncer, RDS Proxy)

## Caching Strategies

### Read and Write Patterns

| Pattern | How it works | Use when |
|---|---|---|
| **Cache-aside** (lazy) | App checks cache, on miss reads origin and populates | Default choice; read-heavy |
| **Read-through** | Cache layer itself loads on miss | You want the load path in one place |
| **Write-through** | Write goes to cache and origin together | Reads must never see stale value |
| **Write-behind** | Write hits cache, origin updated async | Write-heavy, origin is bottleneck |

### Cache Checklist
- [ ] The cached call was measured as expensive first
- [ ] Cache key includes every input the response varies on: tenant, viewer, locale, permissions
- [ ] No per-user data cached under a key that does not identify the user
- [ ] One invalidation strategy chosen (TTL, event/tag, or versioned keys)
- [ ] Acceptable staleness window written down
- [ ] Stampede protection on hot keys (coalescing, lock, or `stale-while-revalidate`)
- [ ] Negative results cached with a shorter TTL; origin errors never cached
- [ ] Eviction policy and memory ceiling set
- [ ] Hit rate monitored
- [ ] Nothing cached whose staleness is a correctness bug (balances, permissions, inventory)

## Async and Concurrency

```python
# Good: async I/O, non-blocking
@app.get("/items/{item_id}")
async def get_item(item_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Item).where(Item.id == item_id))
    return result.scalar_one_or_none()

# Bad: blocking I/O inside async handler
@app.get("/items/{item_id}")
async def get_item(item_id: int):
    time.sleep(1)  # Blocks the event loop!
    return db.query(Item).filter(Item.id == item_id).first()  # Sync ORM in async!
```

- [ ] All database calls are async (`await db.execute(...)`)
- [ ] No `time.sleep()` in async handlers — use `asyncio.sleep()`
- [ ] Background tasks use FastAPI's `BackgroundTasks` or a proper queue (Celery, ARQ)
- [ ] Heavy CPU work offloaded to `run_in_executor` or a task queue

## Common Anti-Patterns

| Anti-Pattern | Impact | Fix |
|---|---|---|
| N+1 queries | Linear DB load growth | Use joins, selectinload, or batch loading |
| Unbounded queries | Memory exhaustion, timeouts | Always paginate, add LIMIT |
| Missing indexes | Slow reads as data grows | Add indexes for filtered/sorted columns |
| Indexing without reading the plan | Write cost paid, read gain unproven | `EXPLAIN ANALYZE` before and after |
| Sync ORM in async handler | Blocks event loop | Use async ORM (SQLAlchemy async) |
| Connection pool per request | Exhausts `max_connections` | One pool per process |
| Cache key missing the viewer | One user's data served to another | Key on tenant, viewer, locale, permissions |
| Unbounded cache | Memory leak | Set eviction policy and a memory ceiling |
| Cache stampede on a hot key | Origin takes full concurrent load | Coalesce misses or `stale-while-revalidate` |
