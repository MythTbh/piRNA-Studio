"""Native-tool checks run on actual Windows and macOS CI machines."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from . import external, inputs, pipeline
from .test_workflow import NATIVE, positive_control


@unittest.skipUnless(NATIVE, 'Native research dependencies are required')
class NativeTests(unittest.TestCase):
    def test_direct_positive_control_without_symlinks(self):
        # Spaces exercise quoting of Windows executable paths and job folders.
        with TemporaryDirectory(prefix='piRNA native check ') as tmp:
            folder = Path(tmp)
            cfg = positive_control(folder)
            with patch.object(Path, 'symlink_to', side_effect=AssertionError('No privileged symlinks')):
                result = pipeline.run(inputs.load_config(cfg), folder / 'direct output')
            self.assertEqual(len(result['clusters']), 1)
            self.assertGreater(result['validation']['jaccard'], 0.98)
            self.assertEqual(result['validation']['recall'], 1)
            self.assertIn('2.4.2', result['provenance']['tools']['PROTRAC_PL'])

    def test_alignment_copy_fallback(self):
        # A blank map needs no caller, while a real positive control exercises fallback.
        with TemporaryDirectory(prefix='piRNA copy check ') as tmp:
            folder = Path(tmp)
            cfg = inputs.load_config(positive_control(folder))
            with patch.object(external.os, 'link', side_effect=OSError('Filesystem has no hard links')):
                result = pipeline.run(cfg, folder / 'copied output')
            self.assertEqual(len(result['clusters']), 1)


if __name__ == '__main__':
    unittest.main()
