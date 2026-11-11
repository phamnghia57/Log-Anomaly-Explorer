import random
import subprocess
import sys
from pathlib import Path
import pytest

class Shuffled:
    def pytest_collection_modifyitems(self, items):
        random.Random(15015).shuffle(items)

if __name__ == '__main__':
    raise SystemExit(pytest.main(['-q', 'query-api/tests'], plugins=[Shuffled()]))
