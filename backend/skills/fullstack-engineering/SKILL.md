---
name: fullstack-engineering
description: Web application development covering API design, frontend, backend, databases, and DevOps
---
# Full-Stack Engineering & Architecture

**Domain:** Web Application Development  
**Scope:** API design, frontend, backend, databases, DevOps

## API Design Principles

### REST Maturity Model
1. Level 0: HTTP as transport only (RPC over HTTP)
2. Level 1: Resources (URIs represent entities)
3. Level 2: Resources + HTTP verbs (GET, POST, PUT, DELETE)
4. Level 3: HATEOAS (hypermedia as engine of state)

**Agentop standard:** Level 2 minimum. RESTful semantics.

### Versioning Strategy
- Prefer URL path versioning (`/api/v1/`..., `/api/v2/`...)
- Semantic versioning for APIs (Major.Minor.Patch)
- Deprecation windows: announce 6+ months before removal
- Multiple versions supported simultaneously

## Frontend Architecture

### Component Patterns
- **Container components** (smart) = handle state, business logic
- **Presentational components** (dumb) = render only, receive props
- Composition over inheritance; hooks over class components

### State Management
- **Local state:** Component-level (using `useState` in React)
- **Shared state:** Context API or centralized store (Redux, Zustand)
- **Global state:** Consider: frequency of changes, number of consumers, performance impact
- **Server state:** Keep in server (database), don't duplicate client-side unnecessarily

### Performance
- Code-splitting by route
- Lazy-load images (native `loading="lazy"`)
- Bundle analysis (`npm run build && npm run analyze`)
- Web Vitals monitoring (LCP, FID, CLS)

## Backend Patterns

### Service Layers
```
Controller (HTTP endpoint)
  ↓
Service (business logic)
  ↓
Repository (data access)
  ↓
Database
```

### Error Handling
- Validation at entry (controller)
- Business logic exceptions catch specific errors
- HTTP status codes match intent (400, 404, 500, etc.)
- Error responses include client-facing message + unique reference ID

### Authentication & Authorization
- Authentication = who you are (login)
- Authorization = what you can do (permissions)
- Prefer stateless tokens (JWT) for APIs
- Rotate secrets regularly; never commit to git

## Database Design

### Normal Forms
- **1NF:** Atomic values, no repeating groups
- **2NF:** 1NF + no partial dependencies
- **3NF:** 2NF + no transitive dependencies
- **BCNF:** Stricter 3NF (rarely needed)

### Indexing Strategy
- Index primary keys (automatic)
- Index foreign keys
- Index frequently queried columns
- Index high-selectivity columns (many unique values)
- Avoid over-indexing (slows writes)

### Migration Strategy
- Backward-compatible migrations first
- Test against production-scale data
- Plan rollback path before deploy
- Document schema changes in version control

## Testing Strategy

### Test Pyramid
```
     /\
    /  \  E2E tests (few)
   /----\
  /      \  Integration tests (some)
 /--------\
/          \ Unit tests (many)
```

### Coverage Targets
- Unit: 70-80% of business logic
- Integration: Core workflows, API boundaries
- E2E: Happy paths, critical user journeys

## Deployment Patterns

### Blue-Green Deployment
- Run two identical production environments (blue, green)
- Route traffic to blue; deploy to green
- Switch traffic when green is verified
- Instant rollback by switching back to blue
- Zero downtime

### Database Migration Sequence
1. Deploy backward-compatible schema changes
2. Deploy application code
3. Clean up old columns (separate deploy, if needed)

### Monitoring & Alerting
- Application logs (structured JSON)
- Error rate threshold alerts
- Response time percentile tracking (p50, p95, p99)
- Database slow query logs
- Infrastructure metrics (CPU, memory, disk, network)

## Key Takeaways

- Full-stack architecture must be component-based, layered, and testable
- Clear separation: HTTP ↔ Service ↔ Data
- State management decisions scale with app complexity
- Migrations: backward-compatible first, test at scale
- Testing: unit > integration > E2E (by count)
