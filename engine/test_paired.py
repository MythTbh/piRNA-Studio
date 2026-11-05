import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from . import paired, inputs, pipeline, science

INSERT = 'TGACCTAGCTAGGTCACGATTCGATGCA'
def record(seq, name='x', quality='I'):
    return name, seq, quality * len(seq)
def write(path, seq, name='x'):
    path.write_text(f'@{name}\n{seq}\n+\n'+ 'I'*len(seq)+'\n')

class PairedTests(unittest.TestCase):
    def test_readthrough_and_partial_overlap(self):
        self.assertEqual(paired.merge_pair(record(INSERT+'AGATCGGAAGAGC'),record(science.rc(INSERT)+'TGGAATTCTCGG')), INSERT)
        self.assertEqual(paired.merge_pair(record(INSERT[:22]),record(science.rc(INSERT[-22:]))), INSERT)
        self.assertIsNone(paired.merge_pair(record('A'*25),record('C'*25)))

    def test_quality_consensus(self):
        changed = 'A' + INSERT[1:]
        self.assertEqual(paired.merge_pair(record(changed,quality='!'), record(science.rc(INSERT))),INSERT)
        self.assertEqual(paired.merge_pair(record(changed), record(science.rc(INSERT))),'N'+INSERT[1:])

    def test_paired_files_and_counts(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp); a=folder/'r1.fq'; b=folder/'r2.fq'
            write(a,INSERT+'AGATCGGAAGAGC','x/1');write(b,science.rc(INSERT)+'TGGAATTCTCGG','x/2')
            sample=dict(sample_id='s',condition='C',replicate=1,layout='paired',fastq_path=str(a),fastq_r2_path=str(b))
            total,hist,counts=pipeline.trim_collapse(sample,inputs.DEFAULTS,folder)
            self.assertEqual(total,1);self.assertEqual(counts,{INSERT:1})
            self.assertEqual(hist,{len(INSERT):1})
            write(b,science.rc(INSERT),'wrong')
            with self.assertRaisesRegex(ValueError,'identif'):list(paired.read_pairs(a,b))
            b.write_text('')
            with self.assertRaisesRegex(ValueError,'counts'):list(paired.read_pairs(a,b))
            sample['fastq_r2_path']=str(a)
            with self.assertRaisesRegex(ValueError,'different'):inputs.is_paired(sample)
