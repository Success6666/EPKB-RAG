package com.example.rag.security;

import cn.dev33.satoken.SaManager;
import cn.dev33.satoken.stp.StpInterface;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

@Configuration
public class SaTokenSecurityConfig {

    @Bean
    public ApplicationRunner registerStpInterface(StpInterface stpInterface) {
        return args -> SaManager.setStpInterface(stpInterface);
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
