package com.example.rag.config;

import cn.dev33.satoken.interceptor.SaInterceptor;
import cn.dev33.satoken.router.SaRouter;
import cn.dev33.satoken.stp.StpUtil;
import com.example.rag.tenant.TenantInterceptor;
import jakarta.servlet.DispatcherType;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

    private final TenantInterceptor tenantInterceptor;

    public WebMvcConfig(TenantInterceptor tenantInterceptor) {
        this.tenantInterceptor = tenantInterceptor;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        SaInterceptor saInterceptor = new SaInterceptor(handler -> SaRouter.match("/api/**")
                .notMatch("/api/auth/**")
                .notMatch("/api/health")
                .notMatch("/api/documents/internal/**")
                .notMatch("/error")
                .check(r -> StpUtil.checkLogin()));
        registry.addInterceptor(new RequestOnlyInterceptor(tenantInterceptor))
            .addPathPatterns("/api/**")
            .excludePathPatterns("/error");
        registry.addInterceptor(new RequestOnlyInterceptor(saInterceptor))
            .addPathPatterns("/**");
    }

    private static class RequestOnlyInterceptor implements HandlerInterceptor {
        private final HandlerInterceptor delegate;

        private RequestOnlyInterceptor(HandlerInterceptor delegate) {
            this.delegate = delegate;
        }

        @Override
        public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
            if (request.getDispatcherType() != DispatcherType.REQUEST) {
                return true;
            }
            return delegate.preHandle(request, response, handler);
        }
    }
}
