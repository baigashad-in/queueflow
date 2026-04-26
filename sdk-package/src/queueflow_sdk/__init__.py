# This file makes the directory a package and defines what is available when importing from the package.
# These imports let users write:
# from queueflow_sdk import QueueFlowClient
# instead of:
# from queueflow_sdk.client import QueueFlowClient

from queueflow_sdk.client import QueueFlowClient
from queueflow_sdk.models import Task, Tenant, ApiKey
from queueflow_sdk.exceptions import QueueFlowError, AuthenticationError, NotFoundError, ConflictError


# __all__ controls what gets exported when someone does:
# from queueflow_sdk import *
# It also serves as a clear list of what the package provides.
__all__ = [
    "QueueFlowClient",
    "Task",
    "Tenant",
    "ApiKey",
    "QueueFlowError",
    "AuthenticationError",
    "NotFoundError",
    "ConflictError",
]

# Package version - accessible via queueflow_sdk.__version__
__version__ = "0.1.1"