class QueueFlowError(Exception):
    """Base exception for QueueFlow SDK errors.
    
    Every other exception inherits from this, so users can catch all SDK errors with a single block:
    try:
        # some SDK code
    except QueueFlowError as e:
        print(f"An error occurred: {e.message}, Status Code: {e.status_code}")
    """
    def __init__(self, message: str, status_code: int = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class AuthenticationError(QueueFlowError):
    """Raised when the API key is invalid , missing, or expired.
    Maps to HTTP 401 Unauthorized."""
    pass

class NotFoundError(QueueFlowError):
    """Raised when the requested resource doesn't exist.
    Maps to HTTP 404 Not Found."""
    pass

class ConflictError(QueueFlowError):
    """Raised when an action conflicts with the current state.
    For example, cancelling an already completed task.
    Maps to HTTP 409 Conflict."""
    pass