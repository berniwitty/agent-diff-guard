import sys

import pytest


@pytest.mark.skipif(sys.version_info < (3, 11), reason="needs 3.11")
def test_tomllib():
    import tomllib

    assert tomllib.loads("a = 1") == {"a": 1}
