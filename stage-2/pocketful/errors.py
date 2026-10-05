"""Owns the API error type: an HTTP status plus the spec's error code."""


class ApiError(Exception):
    def __init__(self, status, code, message=None):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code.replace("_", " ")

    def body(self):
        return {"error": {"code": self.code, "message": self.message}}


def malformed(message="malformed request"):
    return ApiError(400, "malformed_request", message)


def invalid(message="validation failed"):
    return ApiError(422, "validation_failed", message)


def not_found(message="not found"):
    return ApiError(404, "not_found", message)


def forbidden(message="forbidden"):
    return ApiError(403, "forbidden", message)


def unauthenticated(message="unauthenticated"):
    return ApiError(401, "unauthenticated", message)
