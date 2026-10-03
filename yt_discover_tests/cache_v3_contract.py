"""Compatibility import for the production cache-v3 migration contract."""

from yt_media_tools.cache_v3_contract import V3ContractViolation, validate_v3_database

__all__ = ["V3ContractViolation", "validate_v3_database"]
