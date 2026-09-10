"""Public FMBridge HTTP contract identifiers."""

CONTRACT_VERSION = "1"
CONTRACT_PATH_PREFIX = f"v{CONTRACT_VERSION}"
CONTRACT_VERSION_HEADER = "X-FM-Analytics-Contract-Version"


def versioned_path(resource: str) -> str:
    """Return a relative path for a resource in the current contract."""

    return f"{CONTRACT_PATH_PREFIX}/{resource.lstrip('/')}"
