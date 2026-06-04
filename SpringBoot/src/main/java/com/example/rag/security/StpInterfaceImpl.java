package com.example.rag.security;

import cn.dev33.satoken.stp.StpInterface;
import cn.dev33.satoken.stp.StpUtil;
import com.example.rag.config.RagProperties;
import com.example.rag.tenant.TenantContext;
import com.example.rag.tenant.UserTenantMembership;
import com.example.rag.tenant.UserTenantMembershipService;
import com.example.rag.user.UserAccount;
import com.example.rag.user.mapper.UserAccountMapper;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

@Component
public class StpInterfaceImpl implements StpInterface {

    private final UserAccountMapper userAccountMapper;
    private final UserTenantMembershipService membershipService;
    private final RagProperties ragProperties;

    public StpInterfaceImpl(
        UserAccountMapper userAccountMapper,
        UserTenantMembershipService membershipService,
        RagProperties ragProperties
    ) {
        this.userAccountMapper = userAccountMapper;
        this.membershipService = membershipService;
        this.ragProperties = ragProperties;
    }

    @Override
    public List<String> getPermissionList(Object loginId, String loginType) {
        UserAccount user = userAccountMapper.selectById(String.valueOf(loginId));
        List<String> permissions = new ArrayList<>();
        if (isPlatformAdmin(user)) {
            permissions.add("tenant:platform");
            permissions.add("model:switch");
        }

        UserTenantMembership membership = currentMembership(user);
        if (membership == null || membership.getRole() == null) {
            return permissions.stream().distinct().toList();
        }

        String tenantRole = normalizeTenantRole(membership.getRole());
        if (SecurityConstants.TENANT_OWNER.equals(tenantRole)) {
            permissions.addAll(List.of(
                "document:upload",
                "document:read",
                "chat:ask",
                "tenant:employees:read",
                "tenant:employees:write",
                "tenant:admin"
            ));
        } else if (SecurityConstants.TENANT_ADMIN.equals(tenantRole)) {
            permissions.addAll(List.of("document:upload", "document:read", "chat:ask"));
        } else {
            permissions.addAll(List.of("document:read", "chat:ask"));
        }
        return permissions.stream().distinct().toList();
    }

    @Override
    public List<String> getRoleList(Object loginId, String loginType) {
        UserAccount user = userAccountMapper.selectById(String.valueOf(loginId));
        List<String> roles = new ArrayList<>();
        if (user != null && user.getRole() != null) {
            roles.add(user.getRole());
        }
        UserTenantMembership membership = currentMembership(user);
        if (membership != null && membership.getRole() != null) {
            roles.add(normalizeTenantRole(membership.getRole()));
        }
        return roles.stream().distinct().toList();
    }

    private UserTenantMembership currentMembership(UserAccount user) {
        if (user == null) {
            return null;
        }
        Long tenantId = TenantContext.tenantIdOrNull();
        if (tenantId == null) {
            tenantId = tenantIdFromRequestHeader();
        }
        if (tenantId == null && StpUtil.isLogin()) {
            tenantId = StpUtil.getSession().getLong("tenantId");
        }
        if (tenantId != null) {
            return membershipService.findActiveMembership(user.getId(), tenantId).orElse(null);
        }
        return membershipService.selectDefaultMembership(user, membershipService.listActiveMemberships(user.getId()))
            .orElse(null);
    }

    private Long tenantIdFromRequestHeader() {
        if (!(RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes attributes)) {
            return null;
        }
        HttpServletRequest request = attributes.getRequest();
        String value = request.getHeader(ragProperties.getTenant().getHeaderName());
        if (!StringUtils.hasText(value)) {
            return null;
        }
        try {
            return Long.parseLong(value);
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    private boolean isPlatformAdmin(UserAccount user) {
        return user != null
            && user.getRole() != null
            && SecurityConstants.GLOBAL_PLATFORM_ADMIN.equalsIgnoreCase(user.getRole());
    }

    private String normalizeTenantRole(String role) {
        if (SecurityConstants.LEGACY_TENANT_ADMIN.equalsIgnoreCase(role)) {
            return SecurityConstants.TENANT_OWNER;
        }
        if (SecurityConstants.LEGACY_TENANT_USER.equalsIgnoreCase(role)) {
            return SecurityConstants.TENANT_EMPLOYEE;
        }
        return role.toLowerCase();
    }
}
