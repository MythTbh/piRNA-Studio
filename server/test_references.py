import gzip
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from .references import ReferenceCache, REFERENCES
from .service import stage_upload, absolute_inputs
from .test_service import form

class ReferenceTests(unittest.TestCase):
    def test_download_checksum_cache_and_staging(self):
        data = gzip.compress(b'>NC_test.1\nACGTACGT\n')
        ref = dict(REFERENCES['fly'], bytes=len(data), md5=hashlib.md5(data).hexdigest())
        with TemporaryDirectory() as tmp, patch.dict(REFERENCES, fly=ref):
            root=Path(tmp);cache=ReferenceCache(root/'cache')
            with patch('server.references.urlopen', return_value=io.BytesIO(data)) as fetch:
                cache._prepare('fly')
                self.assertEqual(cache.status('fly')['status'],'ready')
                self.assertEqual(fetch.call_count,1)
                cache._prepare('fly')
                self.assertEqual(fetch.call_count,1)
            staged=root/'job';staged.mkdir()
            cfg=dict(reference_genome='fly',samples=[dict(sample_id='a',condition='C',replicate=1,fastq_path='a.fq')])
            headers,body=form(cfg,[('a.fq','@x\nACGT\n+\nIIII\n')])
            config=stage_upload(body,headers['content-type'],staged)
            config['genome'],config['reference_assembly']=cache.attach('fly',staged)
            absolute=absolute_inputs(config,staged)
            self.assertEqual(Path(absolute['genome']).read_bytes(),data)
            self.assertEqual(config['reference_assembly']['accession'],ref['accession'])
            self.assertEqual(config['reference_assembly']['sha256'],hashlib.sha256(data).hexdigest())
            # Failed / truncated downloads must never become available for a run.
            cache2=ReferenceCache(root/'bad')
            with patch('server.references.urlopen',return_value=io.BytesIO(data[:-1])):
                cache2._prepare('fly')
            self.assertEqual(cache2.status('fly')['status'],'failed')
            self.assertFalse(list((root/'bad').glob('*.gz')))
            with self.assertRaises(ValueError):cache2.attach('fly',staged)
            with self.assertRaises(ValueError):cache.prepare('../../bad')
