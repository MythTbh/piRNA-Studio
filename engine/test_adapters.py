"""Adapter pre-flight must predict the actual trimming command."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from . import inputs


class AdapterTests(unittest.TestCase):
    def test_presets(self):
        self.assertEqual(inputs.adapter({'library_kit': 'NEBNext Low-bias'}),
                         'AGATCGGAAGAGCACACGTCTGAACTCCAGTCA')
        self.assertEqual(inputs.adapter({'library_kit': 'NEBNext'}),
                         'AGATCGGAAGAGCACACGTCT')
        self.assertEqual(inputs.adapter({'library_kit': 'Illumina Small RNA v1.5'}),
                         'ATCTCGTATGCCGTCTTCTGCTTG')
        self.assertEqual(inputs.adapter({'library_kit': 'acguacgu'}), 'ACGTACGT')
        with self.assertRaises(ValueError):
            inputs.adapter({'library_kit': 'unknown kit'})

    def test_cli_parity_and_warnings(self):
        adapter = inputs.ADAPTERS['truseq']
        insert = 'ACGT' * 7
        reads = [insert + adapter, insert + adapter[:8],
                 insert + adapter[:7] + 'A' + adapter[8:],
                 insert + adapter[:7] + 'A' + adapter[7:], 'C' * 28]
        positions = inputs.adapter_positions(reads, adapter, 'protrac')
        self.assertEqual(positions, [28, 28, 28, 28, -1])
        self.assertEqual(inputs.adapter_positions(reads, adapter, 'portable'),
                         [28, -1, -1, -1, -1])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            fastq = folder / 'reads.fastq'
            def write_reads(sequences):
                fastq.write_text(''.join(f'@r{i}\n{r}\n+\n' + 'I'*len(r) + '\n'
                                         for i, r in enumerate(sequences)))
            write_reads(reads)
            trimmed = folder / 'trimmed.fastq'
            subprocess.run([sys.executable, '-m', 'cutadapt', '-a', adapter,
                            '--discard-untrimmed', '-o', str(trimmed), str(fastq)],
                           check=True, capture_output=True)
            self.assertEqual([len(r) for r in inputs.fastq(trimmed)],
                             [p for p in positions if p >= 0])
            genome = folder / 'genome.fa'
            genome.write_text('>chr1\n' + insert * 10 + '\n')
            config = dict(genome=str(genome), params={'backend': 'protrac', 'adapter_mode': 'require'},
                          samples=[dict(sample_id='s1', condition='Control', replicate=1,
                                        fastq_path=str(fastq), library_kit='TruSeq')])
            def checks():
                return {r['name']: r for r in inputs.preflight(config, check_tools=False)}
            rows = checks()
            self.assertEqual(rows['s1 adapter']['severity'], 'pass')
            self.assertTrue(rows['s1 lengths']['message'].startswith('80%'))
            self.assertEqual(rows['s1 lengths']['histogram'], {28: 4})
            write_reads(['C'*28])
            rows = checks()
            self.assertEqual(rows['s1 adapter']['severity'], 'warning')
            self.assertEqual(rows['s1 lengths']['severity'], 'warning')
            self.assertEqual(rows['s1 lengths']['histogram'], {})
            self.assertIn('Unmatched read lengths', rows['s1 lengths']['fix'])
            write_reads([insert + inputs.ADAPTERS['illuminasmallrnav15']])
            self.assertIn('illuminasmallrnav15: 100%', checks()['s1 adapter']['fix'])
            self.assertEqual(config['samples'][0]['library_kit'], 'TruSeq')

    def test_preprocessed_and_mixed_libraries(self):
        from .pipeline import trim_collapse
        import os
        from unittest.mock import patch
        adapter = inputs.ADAPTERS['truseq']
        short = 'ACGT' * 5 + 'AC'
        target = 'ACGT' * 7
        long = 'ACGT' * 10
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / 'reads.fastq'
            reads = [short, target + adapter, long]
            source.write_text(''.join(f'@r{i}\n{r}\n+\n' + 'I'*len(r) + '\n'
                                      for i, r in enumerate(reads)))
            sample = dict(sample_id='s', fastq_path=str(source), library_kit='TruSeq',
                          condition='C', replicate=1)
            genome = folder / 'genome.fa'
            genome.write_text('>chr1\n' + target*10 + '\n')
            with patch.dict(os.environ, {'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']}):
                for backend in ('portable', 'protrac'):
                    for mode in ('retain', 'require', 'skip'):
                        for length_filter in ('all', 'range'):
                            params = {**inputs.DEFAULTS, 'backend': backend,
                                      'adapter_mode': mode, 'length_filter': length_filter}
                            total, hist, counts = trim_collapse(sample, params, folder)
                            processed = reads if mode == 'skip' else ([target] if mode == 'require' else [short, target, long])
                            expected = [r for r in processed if length_filter == 'all' or 24 <= len(r) <= 32]
                            self.assertEqual(total, 3)
                            self.assertEqual(dict(counts), {r: 1 for r in expected})
                            rows = inputs.preflight(dict(genome=str(genome), samples=[sample], params=params), check_tools=False)
                            length_row = next(r for r in rows if r['name'] == 's lengths')
                            self.assertEqual(length_row['histogram'], dict(hist))
                            self.assertFalse(any(r['severity'] == 'error' for r in rows))
            # Missing adapters with the new UI defaults must retain a 22 nt library.
            source.write_text('@r0\n' + short + '\n+\n' + 'I'*len(short) + '\n')
            params = {**inputs.DEFAULTS, 'adapter_mode': 'retain', 'length_filter': 'all'}
            self.assertEqual(trim_collapse(sample, params, folder)[2], {short: 1})

    def test_unfiltered_qc_does_not_label_all_reads_pirna_sized(self):
        from .pipeline import qc_profile
        from .science import Hit
        params = {**inputs.DEFAULTS, 'length_filter': 'all'}
        counts = {'ACGT': 2, 'ACGT' * 7: 1, 'ACGT' * 10: 7}
        hits = [Hit('chr', 0, len(seq), '+', seq, n, 1) for seq, n in counts.items()]
        qc, _ = qc_profile('s', 10, {4: 2, 28: 1, 40: 7}, counts, hits, params)
        self.assertEqual(qc['piRNA_range_pct'], 10)
        self.assertEqual(qc['status'], 'warning')
