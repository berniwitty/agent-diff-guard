import sys

import pytest


@pytest.mark.skipif(sys.version_info < (3, 12), reason="needs 3.12")
def test_tomllib():
    import tomllib

    assert tomllib.loads("a = 1") == {"a": 1}
