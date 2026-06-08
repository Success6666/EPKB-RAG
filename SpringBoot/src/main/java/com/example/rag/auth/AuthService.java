package com.example.rag.auth;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.rag.auth.dto.LoginRequest;
import com.example.rag.auth.dto.LoginResponse;
import com.example.rag.auth.dto.RegisterRequest;
import com.example.rag.common.exception.BizException;
import com.example.rag.security.SecurityConstants;
import com.example.rag.tenant.Tenant;
import com.example.rag.tenant.TenantGroup;
import com.example.rag.tenant.UserTenantMembership;
import com.example.rag.tenant.UserTenantMembershipService;
import com.example.rag.tenant.mapper.TenantGroupMapper;
import com.example.rag.tenant.mapper.TenantMapper;
import com.example.rag.tenant.mapper.UserTenantMembershipMapper;
import com.example.rag.user.UserAccount;
import com.example.rag.user.mapper.UserAccountMapper;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.UUID;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
public class AuthService {

    private final UserAccountMapper userAccountMapper;
    private final TenantMapper tenantMapper;
    private final TenantGroupMapper tenantGroupMapper;
    private final UserTenantMembershipMapper membershipMapper;
    private final UserTenantMembershipService membershipService;
    private final PasswordEncoder passwordEncoder;

    public AuthService(
        UserAccountMapper userAccountMapper,
        TenantMapper tenantMapper,
        TenantGroupMapper tenantGroupMapper,
        UserTenantMembershipMapper membershipMapper,
        UserTenantMembershipService membershipService,
        PasswordEncoder passwordEncoder
    ) {
        this.userAccountMapper = userAccountMapper;
        this.tenantMapper = tenantMapper;
        this.tenantGroupMapper = tenantGroupMapper;
        this.membershipMapper = membershipMapper;
        this.membershipService = membershipService;
        this.passwordEncoder = passwordEncoder;
    }

    public LoginResponse login(LoginRequest request) {
        UserAccount user = userAccountMapper.selectOne(new LambdaQueryWrapper<UserAccount>()
            .eq(UserAccount::getUsername, request.username())
            .eq(UserAccount::getStatus, 1)
            .last("limit 1"));
        if (user == null || !passwordMatches(request.password(), user.getPasswordHash())) {
            throw new BizException(401, "Invalid username or password.");
        }
        upgradeLegacyPasswordHash(user, request.password());

        List<UserTenantMembership> memberships = membershipService.listActiveMemberships(user.getId());
        UserTenantMembership defaultMembership = membershipService.selectDefaultMembership(user, memberships).orElse(null);
        if (defaultMembership == null && !isPlatformAdmin(user)) {
            throw new BizException(403, "User has no active tenant membership.");
        }
        return createLoginResponse(user, memberships, defaultMembership);
    }

    @Transactional
    public LoginResponse register(RegisterRequest request) {
        String username = normalizeRequired(request.username(), "Username is required.");
        if (userAccountMapper.selectCount(new LambdaQueryWrapper<UserAccount>()
            .eq(UserAccount::getUsername, username)) > 0) {
            throw new BizException(409, "Username already exists.");
        }

        String mode = normalizeRequired(request.mode(), "Register mode is required.");
        LocalDateTime now = LocalDateTime.now();
        Tenant tenant;
        TenantGroup group;
        String tenantRole;
        if ("createCompany".equalsIgnoreCase(mode)) {
            tenant = createTenant(request.companyName(), now);
            group = createDefaultGroup(tenant.getId(), now);
            tenantRole = SecurityConstants.TENANT_OWNER;
        } else if ("joinCompany".equalsIgnoreCase(mode)) {
            tenant = findTenantByCode(request.companyCode());
            group = findOrCreateDefaultGroup(tenant.getId(), now);
            tenantRole = SecurityConstants.TENANT_EMPLOYEE;
        } else {
            throw new BizException(400, "Unsupported register mode.");
        }

        UserAccount user = new UserAccount();
        user.setTenantId(tenant.getId());
        user.setGroupId(group.getId());
        user.setUsername(username);
        user.setPasswordHash(passwordEncoder.encode(request.password()));
        user.setDisplayName(normalizeRequired(request.displayName(), "Display name is required."));
        user.setRole(SecurityConstants.GLOBAL_USER);
        user.setStatus(1);
        user.setDeleted(0);
        user.setCreatedAt(now);
        user.setUpdatedAt(now);
        userAccountMapper.insert(user);

        UserTenantMembership membership = new UserTenantMembership();
        membership.setUserId(user.getId());
        membership.setTenantId(tenant.getId());
        membership.setGroupId(group.getId());
        membership.setRole(tenantRole);
        membership.setStatus(1);
        membership.setDeleted(0);
        membership.setCreatedAt(now);
        membership.setUpdatedAt(now);
        membershipMapper.insert(membership);

        return createLoginResponse(user, List.of(membership), membership);
    }

    private LoginResponse createLoginResponse(
        UserAccount user,
        List<UserTenantMembership> memberships,
        UserTenantMembership defaultMembership
    ) {
        UserTenantMembership selectedMembership = defaultMembership == null && !memberships.isEmpty()
            ? selectDefaultMembership(user, memberships)
            : defaultMembership;

        StpUtil.login(user.getId());
        if (selectedMembership != null) {
            StpUtil.getSession().set("tenantId", selectedMembership.getTenantId());
            StpUtil.getSession().set("groupId", selectedMembership.getGroupId());
        }

        List<LoginResponse.TenantView> tenants = memberships.stream()
            .map(member -> {
                Tenant tenant = tenantMapper.selectById(member.getTenantId());
                return tenant == null
                    ? null
                    : new LoginResponse.TenantView(
                        String.valueOf(tenant.getId()),
                        tenant.getName(),
                        tenant.getCode(),
                        member.getRole(),
                        "100 GB"
                    );
            })
            .filter(Objects::nonNull)
            .toList();
        return new LoginResponse(
            StpUtil.getTokenValue(),
            new LoginResponse.UserView(String.valueOf(user.getId()), user.getDisplayName(), user.getUsername(), user.getRole()),
            tenants
        );
    }

    private UserTenantMembership selectDefaultMembership(UserAccount user, List<UserTenantMembership> memberships) {
        return membershipService.selectDefaultMembership(user, memberships)
            .orElseThrow(() -> new BizException(403, "User has no active tenant membership."));
    }

    private boolean isPlatformAdmin(UserAccount user) {
        return user != null
            && user.getRole() != null
            && SecurityConstants.GLOBAL_PLATFORM_ADMIN.equalsIgnoreCase(user.getRole());
    }

    private Tenant createTenant(String companyName, LocalDateTime now) {
        Tenant tenant = new Tenant();
        tenant.setName(normalizeRequired(companyName, "Company name is required."));
        tenant.setCode(generateCompanyCode());
        tenant.setStatus(1);
        tenant.setDeleted(0);
        tenant.setCreatedAt(now);
        tenant.setUpdatedAt(now);
        tenantMapper.insert(tenant);
        return tenant;
    }

    private Tenant findTenantByCode(String companyCode) {
        String code = normalizeRequired(companyCode, "Company code is required.");
        Tenant tenant = tenantMapper.selectOne(new LambdaQueryWrapper<Tenant>()
            .eq(Tenant::getCode, code)
            .eq(Tenant::getStatus, 1)
            .eq(Tenant::getDeleted, 0)
            .last("limit 1"));
        if (tenant == null) {
            tenant = tenantMapper.selectOne(new LambdaQueryWrapper<Tenant>()
                .apply("lower(code) = {0}", code.toLowerCase(Locale.ROOT))
                .eq(Tenant::getStatus, 1)
                .eq(Tenant::getDeleted, 0)
                .last("limit 1"));
        }
        if (tenant == null) {
            throw new BizException(404, "Company code not found.");
        }
        return tenant;
    }

    private TenantGroup findOrCreateDefaultGroup(Long tenantId, LocalDateTime now) {
        TenantGroup group = tenantGroupMapper.selectOne(new LambdaQueryWrapper<TenantGroup>()
            .eq(TenantGroup::getTenantId, tenantId)
            .eq(TenantGroup::getDeleted, 0)
            .orderByAsc(TenantGroup::getId)
            .last("limit 1"));
        return group == null ? createDefaultGroup(tenantId, now) : group;
    }

    private TenantGroup createDefaultGroup(Long tenantId, LocalDateTime now) {
        TenantGroup group = new TenantGroup();
        group.setTenantId(tenantId);
        group.setName("Default Group");
        group.setParentId(0L);
        group.setDeleted(0);
        group.setCreatedAt(now);
        group.setUpdatedAt(now);
        tenantGroupMapper.insert(group);
        return group;
    }

    private String generateCompanyCode() {
        for (int i = 0; i < 10; i++) {
            String code = ("ENT-" + UUID.randomUUID().toString().replace("-", "").substring(0, 8))
                .toUpperCase(Locale.ROOT);
            if (tenantMapper.selectCount(new LambdaQueryWrapper<Tenant>().eq(Tenant::getCode, code)) == 0) {
                return code;
            }
        }
        throw new BizException(500, "Failed to generate company code.");
    }

    private String normalizeRequired(String value, String message) {
        if (!StringUtils.hasText(value)) {
            throw new BizException(400, message);
        }
        return value.trim();
    }

    private boolean passwordMatches(String raw, String stored) {
        if (stored == null) {
            return false;
        }
        if (stored.startsWith("{noop}")) {
            return stored.equals("{noop}" + raw);
        }
        if (stored.startsWith("$2a$") || stored.startsWith("$2b$") || stored.startsWith("$2y$")) {
            return passwordEncoder.matches(raw, stored);
        }
        return false;
    }

    private void upgradeLegacyPasswordHash(UserAccount user, String rawPassword) {
        if (user.getPasswordHash() == null || !user.getPasswordHash().startsWith("{noop}")) {
            return;
        }
        user.setPasswordHash(passwordEncoder.encode(rawPassword));
        user.setUpdatedAt(LocalDateTime.now());
        userAccountMapper.updateById(user);
    }
}
