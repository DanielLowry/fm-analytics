from __future__ import annotations


class BridgeSourceError(RuntimeError):
    """A configured source cannot provide a valid manager-visible snapshot."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


class BridgeConfigurationError(ValueError):
    """The bridge was configured with an unsupported source or setting."""
