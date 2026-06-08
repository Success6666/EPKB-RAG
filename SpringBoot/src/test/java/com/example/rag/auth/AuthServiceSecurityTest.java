package com.example.rag.auth;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;

import com.example.rag.tenant.UserTenantMembershipService;
import com.example.rag.tenant.mapper.TenantGroupMapper;
import com.example.rag.tenant.mapper.TenantMapper;
import com.example.rag.tenant.mapper.UserTenantMembershipMapper;
import com.example.rag.user.UserAccount;
import com.example.rag.user.mapper.UserAccountMapper;
import java.lang.reflect.Method;
import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

class AuthServiceSecurityTest {

    private final UserAccountMapper userAccountMapper = org.mockito.Mockito.mock(UserAccountMapper.class);
    private final AuthService authService = new AuthService(
        userAccountMapper,
        org.mockito.Mockito.mock(TenantMapper.class),
        org.mockito.Mockito.mock(TenantGroupMapper.class),
        org.mockito.Mockito.mock(UserTenantMembershipMapper.class),
        org.mockito.Mockito.mock(UserTenantMembershipService.class),
        new BCryptPasswordEncoder()
    );

    @Test
    void passwordMatchesAcceptsBcryptAndRejectsPlaintextStorage() throws Exception {
        PasswordEncoder encoder = new BCryptPasswordEncoder();

        assertTrue(passwordMatches("secret-pass", encoder.encode("secret-pass")));
        assertFalse(passwordMatches("secret-pass", "secret-pass"));
    }

    @Test
    void legacyNoopHashIsUpgradedAfterSuccessfulLogin() throws Exception {
        UserAccount user = new UserAccount();
        user.setId(1L);
        user.setPasswordHash("{noop}old-pass");

        upgradeLegacyPasswordHash(user, "old-pass");

        assertFalse(user.getPasswordHash().startsWith("{noop}"));
        assertTrue(passwordMatches("old-pass", user.getPasswordHash()));
        verify(userAccountMapper).updateById(any(UserAccount.class));
    }

    private boolean passwordMatches(String raw, String stored) throws Exception {
        Method method = AuthService.class.getDeclaredMethod("passwordMatches", String.class, String.class);
        method.setAccessible(true);
        return (Boolean) method.invoke(authService, raw, stored);
    }

    private void upgradeLegacyPasswordHash(UserAccount user, String rawPassword) throws Exception {
        Method method = AuthService.class.getDeclaredMethod("upgradeLegacyPasswordHash", UserAccount.class, String.class);
        method.setAccessible(true);
        method.invoke(authService, user, rawPassword);
    }
}
