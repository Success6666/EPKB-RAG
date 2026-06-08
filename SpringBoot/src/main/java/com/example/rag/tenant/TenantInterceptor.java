package com.example.rag.tenant;

import cn.dev33.satoken.stp.StpUtil;
import com.example.rag.config.RagProperties;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.servlet.HandlerInterceptor;

@Component
public class TenantInterceptor implements HandlerInterceptor {

    private final RagProperties ragProperties;
    private final UserTenantMembershipService membershipService;

    public TenantInterceptor(RagProperties ragProperties, UserTenantMembershipService membershipService) {
        this.ragProperties = ragProperties;
        this.membershipService = membershipService;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws IOException {
        if (isPublicPath(request.getRequestURI())) {
            return true;
        }
        if (!StpUtil.isLogin()) {
            response.sendError(HttpServletResponse.SC_UNAUTHORIZED, "Login required.");
            return false;
        }
        Long tenantId;
        Long groupId;
        try {
            tenantId = readLongHeader(request, ragProperties.getTenant().getHeaderName());
            groupId = readLongHeader(request, ragProperties.getTenant().getGroupHeaderName());
        } catch (NumberFormatException ex) {
            response.sendError(HttpServletResponse.SC_BAD_REQUEST, "Invalid tenant or group header.");
            return false;
        }
        if (tenantId == null && StpUtil.isLogin()) {
            tenantId = StpUtil.getSession().getLong("tenantId");
        }
        if (tenantId == null) {
            response.sendError(HttpServletResponse.SC_BAD_REQUEST, "Missing tenant header: " + ragProperties.getTenant().getHeaderName());
            return false;
        }
        UserTenantMembership membership = membershipService.findActiveMembership(StpUtil.getLoginIdAsLong(), tenantId).orElse(null);
        if (membership == null) {
            response.sendError(HttpServletResponse.SC_FORBIDDEN, "Current user is not authorized for tenant " + tenantId);
            return false;
        }
        if (groupId != null && membership.getGroupId() != null && !membership.getGroupId().equals(groupId)) {
            response.sendError(HttpServletResponse.SC_FORBIDDEN, "Current user is not authorized for group " + groupId);
            return false;
        }
        Long effectiveGroupId = groupId == null ? membership.getGroupId() : groupId;
        StpUtil.getSession().set("tenantId", tenantId);
        StpUtil.getSession().set("groupId", effectiveGroupId);
        TenantContext.set(new TenantInfo(tenantId, effectiveGroupId));
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception ex) {
        TenantContext.clear();
    }

    private Long readLongHeader(HttpServletRequest request, String headerName) {
        String value = request.getHeader(headerName);
        if (!StringUtils.hasText(value)) {
            return null;
        }
        return Long.parseLong(value);
    }

    private boolean isPublicPath(String uri) {
        return uri.startsWith("/api/auth/")
            || uri.equals("/api/tenants")
            || uri.equals("/api/tenants/")
            || uri.equals("/api/tenants/companies")
            || uri.equals("/api/health")
            || uri.startsWith("/api/documents/internal/")
            || uri.startsWith("/actuator/");
    }
}
