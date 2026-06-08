# SpringBoot RAG Platform

Spring Boot 3 service for the multi-tenant private knowledge-base RAG platform.

## Scope

- SaToken login and role/permission checks.
- Tenant context from `X-Tenant-Id` and optional `X-Group-Id`.
- Document upload metadata persistence and RabbitMQ indexing message.
- Redis request rate limiting, FAQ cache, and conversation context cache.
- MySQL durable chat sessions/messages with tenant/time indexes for large query volume.
- Flyway-managed schema migrations under `src/main/resources/db/migration`.
- Resilience4j circuit breaker around the FastAPI RAG call.
- Model config listing and activation for cloud/local model switching.

## Run

```powershell
cd E:\AI\SpringBoot
mvn test
mvn package -DskipTests
```

Flyway runs `src/main/resources/db/migration/V*.sql` automatically on startup. `DatabaseSchemaInitializer` is a disabled-by-default legacy compatibility fallback; enable it only with `RAG_SCHEMA_COMPAT_INITIALIZER_ENABLED=true` when repairing an old environment.

Do not rely on a public seed admin account. Migration `V8__disable_default_seed_accounts.sql`
disables the old demo users (`admin@example.com`, `user@example.com`), and new users are
stored with BCrypt password hashes. Create an administrator through a controlled bootstrap
process before exposing the service beyond local development.

## Main APIs

- `POST /api/auth/login`
- `GET /api/tenants`
- `POST /api/documents/upload`
- `GET /api/documents/tasks`
- `POST /api/chat/ask`
- `GET /api/models`
- `PUT /api/models/{modelId}/activate`
- `GET /api/health`

Production UI should prefer `/api/chat/ask` so Java can enforce auth, tenant isolation, rate limiting, circuit breaking, Redis cache, and MySQL persistence before delegating to FastAPI.
