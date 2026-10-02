class FlexBootError(Exception):
    """Expected operational failure suitable for concise CLI output."""


class SafetyError(FlexBootError):
    """A target failed a safety invariant."""


class DependencyError(FlexBootError):
    """A required host command is unavailable."""


class UnsupportedISOError(FlexBootError):
    """No reliable profile matched an ISO."""


class VerificationError(FlexBootError):
    """Installed state is inconsistent."""

