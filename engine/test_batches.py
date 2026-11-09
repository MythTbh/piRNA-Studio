"""Batched native results must agree with a single full-input tool invocation."""
import os
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from collections import Counter
from . import batches, external, inputs
from .test_workflow import NATIVE


@unittest.skipUnless(NATIVE, 'Native dependencies required')
class BatchTests(unittest.TestCase):
    def test_native_equivalence_resume_and_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rng = random.Random(75)
            dna = ''.join(rng.choices('ACGT', k=4000))
            genome = root / 'genome.fa'
            inputs.write_genome(genome, {'chr2': dna, 'chr1': dna[:100]})
            counts = {dna[i:i+28]: i+1 for i in range(0, 240, 20)}
            counts['A'*28] = 4
            single = root / 'single'; single.mkdir()
            external.write_collapsed(single / 'reads.fa', counts)
            external.invoke(['perl', os.environ['DUSTER_PL'], '-i', 'reads.fa'], single)
            expected = {}
            with (single / 'reads.fa.no-dust').open() as f:
                for head in f:
                    expected[next(f).strip()] = int(head[1:])
            batched = root / 'batched'; batched.mkdir()
            with patch.dict(os.environ, {'PIRNA_BATCH_READS': '4'}):
                actual = external.dust(counts, batched)
                self.assertEqual(actual, expected)
                external.write_collapsed(single / 'filtered.fa', expected)
                external.invoke(['perl', os.environ['SRNAMAPPER_PL'], '-input', 'filtered.fa',
                                 '-genome', str(genome), '-alignments', 'best', '-format', 'eland',
                                 '-output', 'aligned.map'], single)
                hits = external.align(actual, genome, batched)
                self.assertTrue(hits)
                def lines(folder):
                    return Counter(tuple(line.split()) for line in (folder / 'aligned.map').read_text().splitlines() if line.strip())
                self.assertEqual(lines(single), lines(batched))
                self.assertTrue(any(h.multiplicity > 1 for h in hits))
                with patch.object(external, 'invoke', side_effect=AssertionError('Cache was not reused')):
                    self.assertEqual(external.dust(counts, batched), expected)
                    self.assertEqual(external.align(actual, genome, batched), hits)
                # Corrupted output must rerun exactly that batch.
                part = next((batched / 'map-batches').glob('*/aligned.map'))
                part.write_text('corrupted\n')
                with patch.object(external, 'invoke', wraps=external.invoke) as invoke:
                    self.assertEqual(external.align(actual, genome, batched), hits)
                    self.assertEqual(invoke.call_count, 1)
                # Changed reference invalidates mapping checkpoints.
                inputs.write_genome(genome, {'chr3': dna})
                with patch.object(external, 'invoke', wraps=external.invoke) as invoke:
                    changed = external.align(actual, genome, batched)
                    self.assertGreater(invoke.call_count, 1)
                    self.assertTrue(all(h.chrom == 'chr3' for h in changed))

    def test_interrupted_batch_has_no_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); genome = root / 'g.fa'
            inputs.write_genome(genome, {'chr': 'ACGT'*30})
            with patch.object(external, 'invoke', side_effect=RuntimeError('interrupted')):
                with self.assertRaises(RuntimeError):
                    external.align({'ACGT'*7: 1}, genome, root)
            self.assertFalse(list((root / 'map-batches').glob('*/complete.json')))

    def test_pipeline_retry_reuses_completed_native_steps(self):
        from . import pipeline
        from .test_workflow import positive_control
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = inputs.load_config(positive_control(root))
            out = root / 'output'
            with patch.object(external, 'call', side_effect=RuntimeError('Caller interrupted')):
                with self.assertRaisesRegex(RuntimeError, 'Caller interrupted'):
                    pipeline.run(cfg, out)
            invoke = external.invoke
            def only_caller(command, folder):
                if command[0] == 'cutadapt' or any(str(x).endswith(('sRNAmapper.pl', 'TBr2_duster.pl')) for x in command):
                    raise AssertionError('Completed native work was repeated')
                return invoke(command, folder)
            with patch.object(external, 'invoke', side_effect=only_caller):
                result = pipeline.run(cfg, out)
            self.assertEqual(len(result['clusters']), 1)
            self.assertGreater(result['validation']['jaccard'], 0.98)
