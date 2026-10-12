import unittest

from store import Store


class StoreTest(unittest.TestCase):
    def test_save(self):
        store = Store()
        store.save("a")
        self.assertEqual(store.items, ["a"])
