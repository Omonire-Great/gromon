"""The package's own metadata and public surface."""

from importlib.metadata import version
from types import ModuleType

import gromon


def test_the_version_is_reported():
    assert gromon.__version__


def test_the_version_matches_the_installed_distribution():
    assert gromon.__version__ == version("gromon")


def test_everything_in_all_is_importable():
    missing = [name for name in gromon.__all__ if not hasattr(gromon, name)]
    assert missing == []


def test_all_covers_the_whole_surface():
    public = {
        name
        for name in dir(gromon)
        if not name.startswith("_") and not isinstance(getattr(gromon, name), ModuleType)
    }
    assert public - set(gromon.__all__) == set()
