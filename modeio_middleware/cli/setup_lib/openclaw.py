#!/usr/bin/env python3

from __future__ import annotations

from modeio_middleware.cli.setup_lib.openclaw_common import (
    OPENCLAW_AUTH_MODE_NATIVE,
    OPENCLAW_CONFIG_FILENAMES,
    OPENCLAW_DEFAULT_API_KEY,
    OPENCLAW_DEFAULT_STATE_DIRNAME,
    OPENCLAW_MODEL_ID,
    OPENCLAW_MODEL_NAME,
    OPENCLAW_MODEL_REF,
    OPENCLAW_PROVIDER_ID,
    OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
    OPENCLAW_SUPPORTED_API_FAMILIES,
    default_openclaw_config_path,
    default_openclaw_models_cache_path,
)
from modeio_middleware.cli.setup_lib.openclaw_transaction import (
    apply_openclaw_config_file,
    apply_openclaw_models_cache_file,
    apply_openclaw_provider_route,
    remove_openclaw_models_cache_provider,
    remove_openclaw_provider_route,
    uninstall_openclaw_config_file,
    uninstall_openclaw_models_cache_file,
)

__all__ = [
    'OPENCLAW_AUTH_MODE_NATIVE',
    'OPENCLAW_CONFIG_FILENAMES',
    'OPENCLAW_DEFAULT_API_KEY',
    'OPENCLAW_DEFAULT_STATE_DIRNAME',
    'OPENCLAW_MODEL_ID',
    'OPENCLAW_MODEL_NAME',
    'OPENCLAW_MODEL_REF',
    'OPENCLAW_PROVIDER_ID',
    'OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER',
    'OPENCLAW_SUPPORTED_API_FAMILIES',
    'apply_openclaw_config_file',
    'apply_openclaw_models_cache_file',
    'apply_openclaw_provider_route',
    'default_openclaw_config_path',
    'default_openclaw_models_cache_path',
    'remove_openclaw_models_cache_provider',
    'remove_openclaw_provider_route',
    'uninstall_openclaw_config_file',
    'uninstall_openclaw_models_cache_file',
]
