"""Collect independent copies of existing race cases; do not alter assertions."""
import copy


def pytest_collection_modifyitems(items):
    originals = list(items)
    items[:] = []
    for iteration in range(100):
        for item in originals:
            repeated = copy.copy(item)
            repeated._nodeid = item.nodeid + f"[quality-repeat-{iteration + 1:03}]"
            repeated._request = None
            repeated.funcargs = None
            repeated._report_sections = []
            items.append(repeated)
