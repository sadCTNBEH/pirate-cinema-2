class AppException(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppException):
    def __init__(self, message: str = "Not found", status_code: int = 404):
        super().__init__(message, status_code=status_code)


class ExternalServiceError(AppException):
    def __init__(self, message: str = "External service error", status_code: int = 502):
        super().__init__(message, status_code=status_code)


class ProviderUnavailableError(ExternalServiceError):
    def __init__(self, message: str = "Provider unavailable", status_code: int = 503):
        super().__init__(message, status_code=status_code)


class DatabaseError(AppException):
    def __init__(self, message: str = "Database error", status_code: int = 500):
        super().__init__(message, status_code=status_code)


class PlaybackError(AppException):
    def __init__(self, message: str = "Playback error", status_code: int = 500):
        super().__init__(message, status_code=status_code)
