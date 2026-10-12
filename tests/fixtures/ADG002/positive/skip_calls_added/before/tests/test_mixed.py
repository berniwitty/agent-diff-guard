import unittest

from calc import add, sub


def test_add():
    assert add(2, 3) == 5


class SubTest(unittest.TestCase):
    def test_sub(self):
        self.assertEqual(sub(5, 3), 2)
