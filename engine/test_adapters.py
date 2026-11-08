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
            config = dict(genome=str(genome), params={'backend': 'protrac'},
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
            self.assertIn('Resolve the adapter warning', rows['s1 lengths']['fix'])
            write_reads([insert + inputs.ADAPTERS['illuminasmallrnav15']])
            self.assertIn('illuminasmallrnav15: 100%', checks()['s1 adapter']['fix'])
            self.assertEqual(config['samples'][0]['library_kit'], 'TruSeq')
