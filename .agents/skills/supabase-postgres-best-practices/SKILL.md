---
name: supabase-postgres-best-practices
description: Review PostgreSQL query performance, indexes, connection management, concurrency, locking, and data-access patterns. Use for SQL diagnosis or design tradeoffs; combine with database for Galaris schema changes and back-conventions for ORM implementation.
---
# Supabase Postgres Best Practices

## Galaris integration

This is PostgreSQL guidance, not a requirement to adopt Supabase services or auth functions.
Load `database` for schema work and `back-conventions` for ORM code. The `public` schema is
declared by SQLAlchemy and applied by DbAdmin; translate DDL examples into that model rather
than adding handwritten migrations or running Atlas directly. Preserve existing RBAC and
contextual async sessions; do not replace them with an example RLS or pooling architecture.
Check feature availability against PostgreSQL 17 and the installed pgvector version.
Measure with representative synthetic data and compare plans under the same conditions.
`EXPLAIN ANALYZE` executes its statement: use isolated test data for writes or expensive probes.
Use Docker and existing Make targets; a diagnosis request does not authorize production access.
Numeric performance gains in upstream examples are illustrative, not measurements of Galaris.

Comprehensive performance optimization guide for Postgres, maintained by Supabase. Contains rules across 8 categories, prioritized by impact to guide automated query optimization and schema design.

## When to Apply

Reference these guidelines when:
- Writing SQL queries or designing schemas
- Implementing indexes or query optimization
- Reviewing database performance issues
- Configuring connection pooling or scaling
- Optimizing for Postgres-specific features
- Working with Row-Level Security (RLS)

## Rule Categories by Priority

| Priority | Category | Impact | Prefix |
|----------|----------|--------|--------|
| 1 | Query Performance | CRITICAL | `query-` |
| 2 | Connection Management | CRITICAL | `conn-` |
| 3 | Security & RLS | CRITICAL | `security-` |
| 4 | Schema Design | HIGH | `schema-` |
| 5 | Concurrency & Locking | MEDIUM-HIGH | `lock-` |
| 6 | Data Access Patterns | MEDIUM | `data-` |
| 7 | Monitoring & Diagnostics | LOW-MEDIUM | `monitor-` |
| 8 | Advanced Features | LOW | `advanced-` |

## How to Use

Read individual rule files for detailed explanations and SQL examples:

```
references/query-missing-indexes.md
references/query-partial-indexes.md
references/_sections.md
```

Each rule file contains:
- Brief explanation of why it matters
- Incorrect SQL example with explanation
- Correct SQL example with explanation
- Optional EXPLAIN output or metrics
- Additional context and references
- Supabase-specific notes (when applicable)

## References

- https://www.postgresql.org/docs/current/
- https://supabase.com/docs
- https://wiki.postgresql.org/wiki/Performance_Optimization
- https://supabase.com/docs/guides/database/overview
- https://supabase.com/docs/guides/auth/row-level-security

## Provenance

See [SOURCE.md](SOURCE.md) for the pinned upstream revision, license, and local changes.
