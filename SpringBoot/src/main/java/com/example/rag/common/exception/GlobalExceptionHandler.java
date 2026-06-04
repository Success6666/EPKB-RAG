package com.example.rag.common.exception;

import cn.dev33.satoken.exception.NotLoginException;
import cn.dev33.satoken.exception.NotPermissionException;
import com.example.rag.common.ApiResponse;
import jakarta.validation.ConstraintViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(BizException.class)
    public ResponseEntity<ApiResponse<Void>> handleBizException(BizException ex) {
        return jsonError(resolveBizStatus(ex.getCode()), ex.getCode(), ex.getMessage());
    }

    private HttpStatus resolveBizStatus(int code) {
        HttpStatus status = HttpStatus.resolve(code);
        if (status == null || !status.isError()) {
            return HttpStatus.BAD_REQUEST;
        }
        return status;
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, ConstraintViolationException.class})
    public ResponseEntity<ApiResponse<Void>> handleValidation(Exception ex) {
        return jsonError(HttpStatus.BAD_REQUEST, 400, ex.getMessage());
    }

    @ExceptionHandler(NotLoginException.class)
    public ResponseEntity<ApiResponse<Void>> handleNotLogin(NotLoginException ex) {
        return jsonError(HttpStatus.UNAUTHORIZED, 401, ex.getMessage());
    }

    @ExceptionHandler(NotPermissionException.class)
    public ResponseEntity<ApiResponse<Void>> handleNotPermission(NotPermissionException ex) {
        return jsonError(HttpStatus.FORBIDDEN, 403, ex.getMessage());
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleException(Exception ex) {
        return jsonError(HttpStatus.INTERNAL_SERVER_ERROR, 500, ex.getMessage());
    }

    private ResponseEntity<ApiResponse<Void>> jsonError(HttpStatus status, int code, String message) {
        return ResponseEntity
            .status(status)
            .contentType(MediaType.APPLICATION_JSON)
            .body(ApiResponse.fail(code, message));
    }
}
