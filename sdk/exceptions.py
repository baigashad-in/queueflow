class QueueFlowError(Exception):
    """Base exception for QueueFlow SDK."""
    def __init__(self, message: str, status_code: int = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class AuthenticationError(QueueFlowError):
    """Raised when API key is invalid or missing."""

class NotFoundError(QueueFlowError):
    """Raised when a resource is not found."""
    pass

class ConflictError(QueueFlowError):
    """Raised when an action conflicts with current state."""
    pass