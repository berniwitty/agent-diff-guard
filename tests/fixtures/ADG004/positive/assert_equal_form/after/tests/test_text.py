import unittest

import text


class SlugifyTest(unittest.TestCase):
    def test_spaces(self):
        self.assertEqual(text.slugify("A B"), "a_b")
