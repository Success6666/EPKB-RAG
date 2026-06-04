# Security Notes

## Runtime Secrets

- Do not commit `.env`; it is ignored by Git.
- Replace every `change_me_*` value in `.env.example` before running Compose.
- `docker-compose.yml` requires `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, `REDIS_PASSWORD`, `RABBITMQ_PASSWORD`, `MYSQL_DSN`, and `JAVA_CALLBACK_TOKEN` to be set explicitly.
- Keep `JAVA_CALLBACK_TOKEN` identical in SpringBoot and FastAPI. Internal document status and delete callbacks are rejected when the token is missing or mismatched.

## Network Exposure

- The frontend should call SpringBoot through `/api`; it should not call FastAPI directly in production.
- `FASTAPI_BIND_HOST` defaults to `127.0.0.1` so local host publishing does not bypass Java auth by accident.
- Expose RabbitMQ management, MySQL, Redis, Milvus, and Chroma only on trusted networks.

## Database Migrations

- SpringBoot uses Flyway (`db/migration/V*.sql`) for schema and seed data.
- `DatabaseSchemaInitializer` is a legacy compatibility fallback and is disabled by default.
- Use `RAG_SCHEMA_COMPAT_INITIALIZER_ENABLED=true` only for one-off repair of old environments.

## Default Accounts

- Fresh databases include the seed admin `admin@example.com / admin123` for local bootstrap.
- Rotate or remove this credential before any shared or production deployment.
