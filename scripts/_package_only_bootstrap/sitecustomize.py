"""Install ARC3's package-only path guard in inherited Python processes."""

from scripts.package_only_path_guard import install_from_environment

_GUARD = install_from_environment()
