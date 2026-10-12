import unittest

from store import Store


class StoreTest(unittest.TestCase):
    def test_count(self):
        store = Store()
        store.save("a")
        self.assertTrue(store.count())
