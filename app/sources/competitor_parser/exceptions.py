class ExternalParserError(Exception):
    """Base error for external parser integration."""


class ExternalParserConfigError(ExternalParserError):
    """The external parser is missing or incorrectly configured."""


class ExternalParserRunError(ExternalParserError):
    """The external parser process returned an error."""


class ExternalParserTimeoutError(ExternalParserError):
    """The external parser exceeded its configured timeout."""


class ExternalParserOutputNotFoundError(ExternalParserError):
    """The external parser did not produce a fresh CSV file."""
