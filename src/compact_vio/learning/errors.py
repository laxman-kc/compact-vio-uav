"""Errors raised by the optional learned visual-inertial stack."""


class LearningError(ValueError):
    """Raised when a learning contract or artifact is invalid."""


class LearningDependencyError(LearningError):
    """Raised when an explicitly requested optional dependency is unavailable."""


__all__ = ["LearningDependencyError", "LearningError"]
