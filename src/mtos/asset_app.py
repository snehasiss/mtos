"""Canonical application entry point for the MTOS asset service."""

from .app import create_app


def create_asset_app(config=None):
    """Create the electronic/virtual asset-management application."""
    return create_app() if config is None else create_app(config)


__all__ = ["create_asset_app"]
