UPDATE rag_user_account
SET status = 0, updated_at = CURRENT_TIMESTAMP
WHERE username IN ('admin@example.com', 'user@example.com')
  AND password_hash IN ('{noop}admin123', '{noop}user123');

UPDATE rag_user_tenant_membership
SET status = 0, updated_at = CURRENT_TIMESTAMP
WHERE user_id IN (3001, 3002);
