package com.example.rag.config;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "rag.schema-compat-initializer", name = "enabled", havingValue = "true")
public class DatabaseSchemaInitializer implements ApplicationRunner {

    private final JdbcTemplate jdbcTemplate;

    public DatabaseSchemaInitializer(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public void run(ApplicationArguments args) {
        addColumnIfMissing("rag_model_config", "embedding_provider", "embedding_provider VARCHAR(64) NOT NULL DEFAULT 'SentenceTransformers' AFTER api_key");
        addColumnIfMissing("rag_model_config", "embedding_base_url", "embedding_base_url VARCHAR(512) NULL AFTER embedding_model");
        addColumnIfMissing("rag_model_config", "embedding_api_key", "embedding_api_key VARCHAR(1024) NULL AFTER embedding_base_url");
        addColumnIfMissing("rag_model_config", "embedding_input_type", "embedding_input_type VARCHAR(16) NULL AFTER embedding_api_key");
        addColumnIfMissing("rag_model_config", "embedding_truncate", "embedding_truncate VARCHAR(16) NOT NULL DEFAULT 'NONE' AFTER embedding_input_type");
        addColumnIfMissing("rag_model_config", "context_window_tokens", "context_window_tokens INT NOT NULL DEFAULT 262144 AFTER max_tokens");
        normalizeLegacyOllamaEmbeddingDefaults();
        normalizeLegacyDeepSeekModelDefaults();
    }

    private void addColumnIfMissing(String tableName, String columnName, String definition) {
        Integer count = jdbcTemplate.queryForObject(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = ?
              AND COLUMN_NAME = ?
            """,
            Integer.class,
            tableName,
            columnName
        );
        if (count == null || count > 0) {
            return;
        }
        jdbcTemplate.execute("ALTER TABLE " + tableName + " ADD COLUMN " + definition);
    }

    private void normalizeLegacyOllamaEmbeddingDefaults() {
        jdbcTemplate.update(
            """
            UPDATE rag_model_config
            SET embedding_provider = 'SentenceTransformers',
                embedding_model = 'BAAI/bge-small-zh-v1.5',
                embedding_base_url = NULL,
                embedding_input_type = NULL,
                embedding_truncate = 'NONE'
            WHERE deleted = 0
              AND LOWER(embedding_provider) IN ('ollama', 'local')
              AND (embedding_base_url IS NULL OR embedding_base_url LIKE '%host.docker.internal:11434%')
              AND embedding_model IN ('bge-m3', 'nomic-embed-text', 'nomic-embed-text:latest')
            """
        );
    }

    private void normalizeLegacyDeepSeekModelDefaults() {
        jdbcTemplate.update(
            """
            UPDATE rag_model_config legacy
            LEFT JOIN rag_model_config current
              ON current.tenant_id = legacy.tenant_id
             AND current.model_name = 'deepseek-v4-pro'
             AND current.deleted = 0
             AND current.id <> legacy.id
            SET legacy.model_name = 'deepseek-v4-pro'
            WHERE legacy.deleted = 0
              AND LOWER(legacy.provider) = 'deepseek'
              AND legacy.model_name = 'deepseek-chat'
              AND current.id IS NULL
            """
        );
        jdbcTemplate.update(
            """
            UPDATE rag_model_config
            SET rerank_model = 'deepseek-v4-flash'
            WHERE deleted = 0
              AND LOWER(provider) = 'deepseek'
              AND LOWER(rerank_model) IN ('bge-reranker-v2-m3', 'deepseekv4flash', 'deepseek-v4flash', 'deepseek_v4_flash')
            """
        );
    }
}
