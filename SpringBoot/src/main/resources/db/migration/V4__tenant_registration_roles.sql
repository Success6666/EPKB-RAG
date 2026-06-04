UPDATE rag_user_tenant_membership
SET role = 'tenant_owner', updated_at = CURRENT_TIMESTAMP
WHERE role = 'admin';

UPDATE rag_user_tenant_membership
SET role = 'employee', updated_at = CURRENT_TIMESTAMP
WHERE role = 'user';

UPDATE rag_user_account
SET role = 'user', updated_at = CURRENT_TIMESTAMP
WHERE role IS NULL OR role = '';

UPDATE rag_user_account
SET role = 'admin', updated_at = CURRENT_TIMESTAMP
WHERE username = 'admin@example.com';
