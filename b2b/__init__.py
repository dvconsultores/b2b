"""Shared exceptions for the b2b package."""


class InputError(Exception):
    """Raised for a missing file/sheet header; message names file, sheet, headers only."""


class ConfigError(Exception):
    """Raised for a bad config file; message names file and line numbers only."""
