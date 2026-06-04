package com.example.rag.tenant;

import cn.dev33.satoken.annotation.SaCheckPermission;
import com.example.rag.tenant.dto.CompanyListResponse;
import com.example.rag.tenant.dto.EmployeeListResponse;
import com.example.rag.tenant.dto.TenantListResponse;
import com.example.rag.tenant.dto.UpdateEmployeeRoleRequest;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tenants")
public class TenantController {

    private final TenantService tenantService;

    public TenantController(TenantService tenantService) {
        this.tenantService = tenantService;
    }

    @GetMapping
    public TenantListResponse list() {
        return tenantService.listMyTenants();
    }

    @GetMapping("/employees")
    @SaCheckPermission("tenant:employees:read")
    public EmployeeListResponse employees() {
        return tenantService.listEmployees();
    }

    @PutMapping("/employees/{userId}/role")
    @SaCheckPermission("tenant:employees:write")
    public void updateEmployeeRole(
        @PathVariable Long userId,
        @Valid @RequestBody UpdateEmployeeRoleRequest request
    ) {
        tenantService.updateEmployeeRole(userId, request);
    }

    @GetMapping("/companies")
    @SaCheckPermission("tenant:platform")
    public CompanyListResponse companies() {
        return tenantService.listCompanies();
    }
}
