# Security Notes

## Runtime Secrets

- Do not commit `.env`; it is ignored by Git.
- Replace every `change_me_*` value in `.env.example` before running Compose.
- `docker-compose.yml` requires `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, `REDIS_PASSWORD`, `RABBITMQ_PASSWORD`, `MYSQL_DSN`, and `JAVA_CALLBACK_TOKEN` to be set explicitly.
- Keep `JAVA_CALLBACK_TOKEN` identical in SpringBoot and FastAPI. FastAPI document/RAG endpoints require this internal token and reject unauthenticated direct calls.
- Do not use any `change_me_*`, `guest`, or short shared secret value outside local experiments. Generate a strong random `JAVA_CALLBACK_TOKEN` before starting shared environments.

## Network Exposure

- The frontend should call SpringBoot through `/api`; it should not call FastAPI directly in production.
- `FASTAPI_BIND_HOST` defaults to `127.0.0.1` so local host publishing does not bypass Java auth by accident.
- MySQL, Redis, RabbitMQ, RabbitMQ management, Milvus, Milvus metrics, and Chroma bind to `127.0.0.1` by default in Compose. Expose them only on trusted networks or behind VPN/firewall rules.

## Database Migrations

- SpringBoot uses Flyway (`db/migration/V*.sql`) for schema and seed data.
- `DatabaseSchemaInitializer` is a legacy compatibility fallback and is disabled by default.
- Use `RAG_SCHEMA_COMPAT_INITIALIZER_ENABLED=true` only for one-off repair of old environments.

## Default Accounts

- New registrations are stored with BCrypt hashes.
- Legacy `{noop}` password hashes are accepted only for migration and are upgraded after successful login.
- Migration `V8__disable_default_seed_accounts.sql` disables the old demo seed users (`admin@example.com`, `user@example.com`) so shared environments do not keep public bootstrap credentials.
