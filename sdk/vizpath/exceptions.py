"""Custom exceptions for the vizpath SDK."""


class VizpathError(Exception):
    """Base exception for all vizpath errors."""

    pass


class ConfigurationError(VizpathError):
    """Raised when SDK configuration is invalid."""

    pass


class ConnectionError(VizpathError):
    """Raised when connection to the server fails."""

    pass


class AuthenticationError(VizpathError):
    """Raised when API key is invalid or missing."""

    pass


class RateLimitError(VizpathError):
    """Raised when rate limit is exceeded."""

    pass


class TimeoutError(VizpathError):
    """Raised when a request times out."""

    pass
