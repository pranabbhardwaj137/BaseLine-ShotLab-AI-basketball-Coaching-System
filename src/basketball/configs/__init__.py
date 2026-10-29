"""
configs package - Baseline Shot Lab configuration registries.
"""

from basketball.configs.shot_types import (
    CONFIG_VERSION,
    SHOT_TYPE_REGISTRY,
    SHOT_TYPE_ALIASES,
    resolve_shot_type,
    get_shot_type,
    get_all_shot_types,
    validate_shot_types_config,
)

__all__ = [
    "CONFIG_VERSION",
    "SHOT_TYPE_REGISTRY",
    "SHOT_TYPE_ALIASES",
    "resolve_shot_type",
    "get_shot_type",
    "get_all_shot_types",
    "validate_shot_types_config",
]

