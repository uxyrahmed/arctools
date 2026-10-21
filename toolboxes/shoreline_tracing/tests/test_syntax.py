# -*- coding: utf-8 -*-
"""Checks the toolbox code parses as Python 3.9, which ArcGIS Pro 3.0 to 3.2
ship, so no newer syntax slips in. Run from the repository root with:

    python -m unittest discover -s toolboxes/shoreline_tracing/tests
"""

import ast
import glob
import os
import unittest

TOOLBOX = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SyntaxTests(unittest.TestCase):
    def test_parses_as_python_39(self):
        paths = glob.glob(os.path.join(TOOLBOX, "*.pyt"))
        paths += glob.glob(os.path.join(TOOLBOX, "shoreline", "*.py"))
        self.assertTrue(any(path.endswith(".pyt") for path in paths))
        for path in paths:
            with self.subTest(file=os.path.basename(path)):
                with open(path, encoding="utf-8") as source:
                    ast.parse(source.read(), filename=path, feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
