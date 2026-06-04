package com.example.rag.tenant;

public final class TenantContext {

    private static final ThreadLocal<TenantInfo> HOLDER = new ThreadLocal<>();

    private TenantContext() {
    }

    public static void set(TenantInfo tenantInfo) {
        HOLDER.set(tenantInfo);
    }

    public static TenantInfo get() {
        TenantInfo tenantInfo = HOLDER.get();
        if (tenantInfo == null) {
            throw new IllegalStateException("Tenant context is missing");
        }
        return tenantInfo;
    }

    public static Long tenantId() {
        return get().tenantId();
    }

    public static Long tenantIdOrNull() {
        TenantInfo tenantInfo = HOLDER.get();
        return tenantInfo == null ? null : tenantInfo.tenantId();
    }

    public static Long groupId() {
        return get().groupId();
    }

    public static void clear() {
        HOLDER.remove();
    }
}
