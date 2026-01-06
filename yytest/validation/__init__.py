"""Validation module for yeytest."""

from .local import LocalValidator
from .ai import AIValidator

__all__ = ["LocalValidator", "AIValidator"]

