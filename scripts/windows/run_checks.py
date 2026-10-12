"""The minimum relevant suite; does not start services or load embedding weights."""
from pathlib import Path
import sys
import unittest

root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'tests'),str(root)]
suite=unittest.TestLoader().loadTestsFromNames([
    'test_windows_compat','test_local_knowledge','test_content_scope',
])
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
