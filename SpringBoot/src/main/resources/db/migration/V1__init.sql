CREATE TABLE IF NOT EXISTS rag_tenant (
  id BIGINT PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  code VARCHAR(64) NOT NULL,
  status TINYINT NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted TINYINT NOT NULL DEFAULT 0,
  UNIQUE KEY uk_tenant_code (code),
  KEY idx_tenant_status (status, deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rag_tenant_group (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL,
  name VARCHAR(128) NOT NULL,
  parent_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted TINYINT NOT NULL DEFAULT 0,
  KEY idx_group_tenant (tenant_id, deleted),
  KEY idx_group_parent (tenant_id, parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rag_user_account (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL,
  group_id BIGINT NULL,
  username VARCHAR(128) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(128) NOT NULL,
  role VARCHAR(32) NOT NULL,
  status TINYINT NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted TINYINT NOT NULL DEFAULT 0,
  UNIQUE KEY uk_user_username (username),
  KEY idx_user_tenant_role (tenant_id, role, deleted),
  KEY idx_user_group (tenant_id, group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rag_user_tenant_membership (
  id BIGINT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  tenant_id BIGINT NOT NULL,
  group_id BIGINT NULL,
  role VARCHAR(32) NOT NULL,
  status TINYINT NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted TINYINT NOT NULL DEFAULT 0,
  UNIQUE KEY uk_member_user_tenant (user_id, tenant_id, deleted),
  KEY idx_member_tenant_user (tenant_id, user_id, status, deleted),
  KEY idx_member_group (tenant_id, group_id, deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rag_knowledge_base (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL,
  group_id BIGINT NULL,
  name VARCHAR(128) NOT NULL,
  description VARCHAR(512) NOT NULL DEFAULT '',
  visibility TINYINT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted TINYINT NOT NULL DEFAULT 0,
  UNIQUE KEY uk_kb_tenant_name (tenant_id, name, deleted),
  KEY idx_kb_group (tenant_id, group_id, deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rag_document_file (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL,
  group_id BIGINT NULL,
  knowledge_base_id BIGINT NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  content_type VARCHAR(128) NULL,
  file_size BIGINT NOT NULL DEFAULT 0,
  storage_path VARCHAR(1024) NOT NULL,
  status VARCHAR(32) NOT NULL,
  chunk_count INT NOT NULL DEFAULT 0,
  error_message VARCHAR(1024) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted TINYINT NOT NULL DEFAULT 0,
  KEY idx_doc_tenant_kb_status (tenant_id, knowledge_base_id, status, deleted),
  KEY idx_doc_tenant_created (tenant_id, created_at DESC),
  FULLTEXT KEY ft_doc_file_name (file_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rag_chat_session (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  title VARCHAR(255) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted TINYINT NOT NULL DEFAULT 0,
  KEY idx_chat_session_tenant_user_time (tenant_id, user_id, updated_at DESC, deleted),
  KEY idx_chat_session_tenant_time (tenant_id, updated_at DESC, deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rag_chat_message (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL,
  session_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  role VARCHAR(32) NOT NULL,
  content MEDIUMTEXT NOT NULL,
  citations_json JSON NULL,
  prompt_tokens INT NOT NULL DEFAULT 0,
  completion_tokens INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted TINYINT NOT NULL DEFAULT 0,
  KEY idx_msg_tenant_session_time (tenant_id, session_id, created_at),
  KEY idx_msg_tenant_user_session_time (tenant_id, user_id, session_id, created_at),
  KEY idx_msg_tenant_user_time (tenant_id, user_id, created_at DESC),
  FULLTEXT KEY ft_msg_content (content)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rag_model_config (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL,
  provider VARCHAR(64) NOT NULL,
  model_name VARCHAR(128) NOT NULL,
  base_url VARCHAR(512) NULL,
  api_key VARCHAR(1024) NULL,
  embedding_provider VARCHAR(64) NOT NULL DEFAULT 'SentenceTransformers',
  embedding_model VARCHAR(128) NOT NULL,
  embedding_base_url VARCHAR(512) NULL,
  embedding_api_key VARCHAR(1024) NULL,
  embedding_input_type VARCHAR(16) NULL,
  embedding_truncate VARCHAR(16) NOT NULL DEFAULT 'NONE',
  rerank_model VARCHAR(128) NOT NULL DEFAULT 'none',
  temperature DECIMAL(4,2) NOT NULL DEFAULT 0.20,
  top_p DECIMAL(4,2) NOT NULL DEFAULT 0.80,
  max_tokens INT NOT NULL DEFAULT 4096,
  context_window_tokens INT NOT NULL DEFAULT 262144,
  enabled TINYINT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted TINYINT NOT NULL DEFAULT 0,
  UNIQUE KEY uk_model_tenant_name (tenant_id, model_name, deleted),
  KEY idx_model_tenant_enabled (tenant_id, enabled, deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rag_python_document_chunk (
  chunk_id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  kb_id VARCHAR(64) NOT NULL,
  doc_id VARCHAR(128) NOT NULL,
  chunk_index INT NOT NULL DEFAULT 0,
  text MEDIUMTEXT NOT NULL,
  metadata JSON NULL,
  file_name VARCHAR(255) NULL,
  source_uri VARCHAR(1024) NULL,
  page INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (chunk_id),
  KEY idx_py_chunk_scope_doc (tenant_id, kb_id, doc_id),
  KEY idx_py_chunk_scope_index (tenant_id, kb_id, chunk_index),
  FULLTEXT KEY ft_py_chunk_text (text)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rag_python_ingest_job (
  job_key VARCHAR(255) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  kb_id VARCHAR(64) NOT NULL,
  doc_id VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL,
  attempts INT NOT NULL DEFAULT 0,
  chunk_count INT NOT NULL DEFAULT 0,
  error_message VARCHAR(1024) NULL,
  payload JSON NULL,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (job_key),
  KEY idx_py_job_doc (tenant_id, kb_id, doc_id),
  KEY idx_py_job_status (status, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO rag_tenant (id, name, code, status) VALUES
(1001, 'Demo Enterprise', 'demo', 1);

INSERT IGNORE INTO rag_tenant_group (id, tenant_id, name, parent_id) VALUES
(2001, 1001, 'Head Office', NULL);

INSERT IGNORE INTO rag_user_account (id, tenant_id, group_id, username, password_hash, display_name, role, status) VALUES
(3001, 1001, 2001, 'admin@example.com', '{noop}admin123', 'Platform Admin', 'admin', 1),
(3002, 1001, 2001, 'user@example.com', '{noop}user123', 'Knowledge User', 'user', 1);

INSERT IGNORE INTO rag_user_tenant_membership (id, user_id, tenant_id, group_id, role, status) VALUES
(3101, 3001, 1001, 2001, 'admin', 1),
(3102, 3002, 1001, 2001, 'user', 1);

INSERT IGNORE INTO rag_model_config
(id, tenant_id, provider, model_name, embedding_provider, embedding_model, embedding_base_url, embedding_input_type, embedding_truncate, rerank_model, temperature, top_p, max_tokens, enabled)
VALUES
(4001, 1001, 'Ollama', 'qwen2.5:7b', 'SentenceTransformers', 'BAAI/bge-small-zh-v1.5', NULL, NULL, 'NONE', 'none', 0.20, 0.80, 2048, 1),
(4002, 1001, 'DeepSeek', 'deepseek-v4-pro', 'SentenceTransformers', 'BAAI/bge-small-zh-v1.5', NULL, NULL, 'NONE', 'deepseek-v4-flash', 0.30, 0.90, 8192, 0);
