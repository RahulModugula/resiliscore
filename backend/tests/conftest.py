import os

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits the real federal APIs; runs only with RS_LIVE=1")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RS_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="set RS_LIVE=1 to hit the real APIs")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
