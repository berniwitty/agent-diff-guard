import unittest

import pytest
from calc import add, sub


def test_add():
    pytest.skip("todo")
    assert add(2, 3) == 5


class SubTest(unittest.TestCase):
    def test_sub(self):
        self.skipTest("later")
        self.assertEqual(sub(5, 3), 2)
