package com.example.rag.tenant;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.rag.common.exception.BizException;
import com.example.rag.security.SecurityConstants;
import com.example.rag.tenant.dto.CompanyListResponse;
import com.example.rag.tenant.dto.EmployeeListResponse;
import com.example.rag.tenant.dto.TenantListResponse;
import com.example.rag.tenant.dto.UpdateEmployeeRoleRequest;
import com.example.rag.tenant.mapper.TenantMapper;
import com.example.rag.tenant.mapper.UserTenantMembershipMapper;
import com.example.rag.user.UserAccount;
import com.example.rag.user.mapper.UserAccountMapper;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TenantService {

    private final TenantMapper tenantMapper;
    private final UserTenantMembershipMapper membershipMapper;
    private final UserAccountMapper userAccountMapper;
    private final UserTenantMembershipService membershipService;

    public TenantService(
        TenantMapper tenantMapper,
        UserTenantMembershipMapper membershipMapper,
        UserAccountMapper userAccountMapper,
        UserTenantMembershipService membershipService
    ) {
        this.tenantMapper = tenantMapper;
        this.membershipMapper = membershipMapper;
        this.userAccountMapper = userAccountMapper;
        this.membershipService = membershipService;
    }

    public TenantListResponse listMyTenants() {
        return new TenantListResponse(membershipService.listActiveMemberships(StpUtil.getLoginIdAsLong()).stream()
            .map(member -> {
                Tenant tenant = tenantMapper.selectById(member.getTenantId());
                return tenant == null
                    ? null
                    : new TenantListResponse.TenantItem(
                        String.valueOf(tenant.getId()),
                        tenant.getName(),
                        tenant.getCode(),
                        normalizeTenantRole(member.getRole()),
                        "100 GB"
                    );
            })
            .filter(Objects::nonNull)
            .toList());
    }

    public EmployeeListResponse listEmployees() {
        Long tenantId = currentTenantId();
        List<UserTenantMembership> memberships = membershipMapper.selectList(new LambdaQueryWrapper<UserTenantMembership>()
            .eq(UserTenantMembership::getTenantId, tenantId)
            .eq(UserTenantMembership::getStatus, 1)
            .eq(UserTenantMembership::getDeleted, 0)
            .orderByAsc(UserTenantMembership::getCreatedAt));
        if (memberships.isEmpty()) {
            return new EmployeeListResponse(List.of());
        }

        List<Long> userIds = memberships.stream().map(UserTenantMembership::getUserId).distinct().toList();
        Map<Long, UserAccount> users = userAccountMapper.selectBatchIds(userIds)
            .stream()
            .filter(user -> Integer.valueOf(1).equals(user.getStatus()) && Integer.valueOf(0).equals(user.getDeleted()))
            .collect(Collectors.toMap(UserAccount::getId, Function.identity()));

        return new EmployeeListResponse(memberships.stream()
            .map(member -> toEmployeeItem(member, users.get(member.getUserId())))
            .filter(Objects::nonNull)
            .sorted(Comparator.comparing(EmployeeListResponse.EmployeeItem::joinedAt))
            .toList());
    }

    @Transactional
    public void updateEmployeeRole(Long userId, UpdateEmployeeRoleRequest request) {
        if (StpUtil.getLoginIdAsLong() == userId.longValue()) {
            throw new BizException(400, "Cannot change your own tenant role.");
        }
        String role = normalizeAssignableRole(request.role());
        UserTenantMembership membership = membershipMapper.selectOne(new LambdaQueryWrapper<UserTenantMembership>()
            .eq(UserTenantMembership::getTenantId, currentTenantId())
            .eq(UserTenantMembership::getUserId, userId)
            .eq(UserTenantMembership::getStatus, 1)
            .eq(UserTenantMembership::getDeleted, 0)
            .last("limit 1"));
        if (membership == null) {
            throw new BizException(404, "Employee not found.");
        }
        if (SecurityConstants.TENANT_OWNER.equals(normalizeTenantRole(membership.getRole()))) {
            throw new BizException(403, "Company creator role cannot be changed.");
        }
        membership.setRole(role);
        membership.setUpdatedAt(LocalDateTime.now());
        membershipMapper.updateById(membership);
    }

    public CompanyListResponse listCompanies() {
        return new CompanyListResponse(tenantMapper.selectList(new LambdaQueryWrapper<Tenant>()
                .eq(Tenant::getDeleted, 0)
                .orderByDesc(Tenant::getCreatedAt))
            .stream()
            .map(tenant -> new CompanyListResponse.CompanyItem(
                String.valueOf(tenant.getId()),
                tenant.getName(),
                tenant.getCode(),
                tenant.getStatus(),
                tenant.getCreatedAt()
            ))
            .toList());
    }

    private EmployeeListResponse.EmployeeItem toEmployeeItem(UserTenantMembership member, UserAccount user) {
        if (user == null) {
            return null;
        }
        return new EmployeeListResponse.EmployeeItem(
            String.valueOf(user.getId()),
            user.getUsername(),
            user.getDisplayName(),
            normalizeTenantRole(member.getRole()),
            member.getCreatedAt()
        );
    }

    private Long currentTenantId() {
        Long tenantId = TenantContext.tenantIdOrNull();
        if (tenantId == null) {
            tenantId = StpUtil.getSession().getLong("tenantId");
        }
        if (tenantId == null) {
            throw new BizException(400, "Missing tenant context.");
        }
        return tenantId;
    }

    private String normalizeAssignableRole(String role) {
        String normalized = normalizeTenantRole(role);
        if (SecurityConstants.TENANT_ADMIN.equals(normalized) || SecurityConstants.TENANT_EMPLOYEE.equals(normalized)) {
            return normalized;
        }
        throw new BizException(400, "Only employee and tenant_admin roles can be assigned.");
    }

    private String normalizeTenantRole(String role) {
        if (role == null) {
            return SecurityConstants.TENANT_EMPLOYEE;
        }
        if (SecurityConstants.LEGACY_TENANT_ADMIN.equalsIgnoreCase(role)) {
            return SecurityConstants.TENANT_OWNER;
        }
        if (SecurityConstants.LEGACY_TENANT_USER.equalsIgnoreCase(role)) {
            return SecurityConstants.TENANT_EMPLOYEE;
        }
        return role.toLowerCase();
    }
}
