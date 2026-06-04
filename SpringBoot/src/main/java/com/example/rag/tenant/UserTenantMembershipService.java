package com.example.rag.tenant;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.rag.tenant.mapper.TenantMapper;
import com.example.rag.tenant.mapper.UserTenantMembershipMapper;
import com.example.rag.user.UserAccount;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;

@Service
public class UserTenantMembershipService {

    private final UserTenantMembershipMapper membershipMapper;
    private final TenantMapper tenantMapper;

    public UserTenantMembershipService(UserTenantMembershipMapper membershipMapper, TenantMapper tenantMapper) {
        this.membershipMapper = membershipMapper;
        this.tenantMapper = tenantMapper;
    }

    public Optional<UserTenantMembership> findActiveMembership(Long userId, Long tenantId) {
        if (userId == null || tenantId == null) {
            return Optional.empty();
        }
        UserTenantMembership membership = membershipMapper.selectOne(new LambdaQueryWrapper<UserTenantMembership>()
            .eq(UserTenantMembership::getUserId, userId)
            .eq(UserTenantMembership::getTenantId, tenantId)
            .eq(UserTenantMembership::getStatus, 1)
            .eq(UserTenantMembership::getDeleted, 0)
            .last("limit 1"));
        if (membership == null || !isActiveTenant(tenantId)) {
            return Optional.empty();
        }
        return Optional.of(membership);
    }

    public List<UserTenantMembership> listActiveMemberships(Long userId) {
        if (userId == null) {
            return List.of();
        }
        List<UserTenantMembership> memberships = membershipMapper.selectList(new LambdaQueryWrapper<UserTenantMembership>()
            .eq(UserTenantMembership::getUserId, userId)
            .eq(UserTenantMembership::getStatus, 1)
            .eq(UserTenantMembership::getDeleted, 0)
            .orderByAsc(UserTenantMembership::getTenantId));
        if (memberships.isEmpty()) {
            return List.of();
        }
        Set<Long> activeTenantIds = tenantMapper.selectList(new LambdaQueryWrapper<Tenant>()
                .in(Tenant::getId, memberships.stream().map(UserTenantMembership::getTenantId).collect(Collectors.toSet()))
                .eq(Tenant::getStatus, 1)
                .eq(Tenant::getDeleted, 0))
            .stream()
            .map(Tenant::getId)
            .collect(Collectors.toSet());
        return memberships.stream()
            .filter(membership -> activeTenantIds.contains(membership.getTenantId()))
            .sorted(Comparator.comparing(UserTenantMembership::getTenantId))
            .toList();
    }

    public Optional<UserTenantMembership> selectDefaultMembership(UserAccount user, List<UserTenantMembership> memberships) {
        if (memberships == null || memberships.isEmpty()) {
            return Optional.empty();
        }
        if (user != null && user.getTenantId() != null) {
            Optional<UserTenantMembership> defaultMembership = memberships.stream()
                .filter(membership -> user.getTenantId().equals(membership.getTenantId()))
                .findFirst();
            if (defaultMembership.isPresent()) {
                return defaultMembership;
            }
        }
        return Optional.of(memberships.get(0));
    }

    private boolean isActiveTenant(Long tenantId) {
        return tenantMapper.selectCount(new LambdaQueryWrapper<Tenant>()
            .eq(Tenant::getId, tenantId)
            .eq(Tenant::getStatus, 1)
            .eq(Tenant::getDeleted, 0)) > 0;
    }
}
