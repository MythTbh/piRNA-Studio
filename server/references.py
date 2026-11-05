"""Version-pinned NCBI reference downloads, verified before use."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
from datetime import datetime, timezone
from urllib.request import Request, urlopen

CATALOG = json.loads((Path(__file__).resolve().parents[1] / 'engine/reference_catalog.json').read_text())
REFERENCES = {r['id']: r for r in CATALOG}


def reference(key):
    if not isinstance(key, str) or key not in REFERENCES:
        raise ValueError('Choose a supported NCBI reference organism')
    return REFERENCES[key]


class ReferenceCache:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.slot = threading.Semaphore(1)
        self.states = {}

    def status(self, key):
        ref = reference(key)
        with self.lock:
            return dict(self.states.get(key, dict(status='not_ready', downloaded_bytes=0, total_bytes=ref['bytes'])))

    def update(self, key, **values):
        with self.lock:
            self.states.setdefault(key, {}).update(values)

    def prepare(self, key):
        ref = reference(key)
        with self.lock:
            if self.status(key)['status'] not in {'queued', 'downloading', 'verifying', 'ready'}:
                self.states[key] = dict(status='queued', downloaded_bytes=0, total_bytes=ref['bytes'], error='')
                threading.Thread(target=self._prepare, args=(key,), daemon=True).start()
            return self.status(key)

    def _prepare(self, key):
        ref = reference(key)
        target = self.directory / (ref['accession'] + '.fna.gz')
        partial = target.with_suffix('.part')
        try:
            with self.slot:
                self.update(key, status='verifying')
                valid = False
                if target.is_file():
                    with target.open('rb') as stream:
                        valid = hashlib.file_digest(stream, 'md5').hexdigest() == ref['md5']
                if not valid:
                    self.update(key, status='downloading')
                    digest = hashlib.md5()
                    sha = hashlib.sha256()
                    count = 0
                    req = Request(ref['url'], headers={'User-Agent': 'piRNA-Studio/1.1 (reference-genome-download)'})
                    with urlopen(req, timeout=60) as response, partial.open('wb') as stream:
                        while block := response.read(1024 * 1024):
                            count += len(block)
                            if count > ref['bytes']:
                                raise ValueError('NCBI download exceeds the expected assembly size')
                            digest.update(block); sha.update(block); stream.write(block)
                            self.update(key, downloaded_bytes=count)
                    if count != ref['bytes'] or digest.hexdigest() != ref['md5']:
                        raise ValueError('NCBI reference checksum mismatch; retry the download')
                    self.update(key, status='verifying')
                    # Check gzip integrity to EOF without loading a whole genome into RAM.
                    with gzip.open(partial, 'rb') as stream:
                        if stream.read(1) != b'>':
                            raise ValueError('NCBI reference is not a FASTA file')
                        while stream.read(1024 * 1024):
                            pass
                    os.replace(partial, target)
                    checksum = sha.hexdigest()
                else:
                    with target.open('rb') as stream:
                        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
                info = dict(ref, sha256=checksum, verified_at=datetime.now(timezone.utc).isoformat())
                self.update(key, status='ready', downloaded_bytes=ref['bytes'], metadata=info)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            self.update(key, status='failed', error=f'Reference download failed: {exc}. Check your connection and available disk space, then retry.')

    def attach(self, key, staged):
        ref = reference(key)
        state = self.status(key)
        if state['status'] != 'ready':
            raise ValueError('Download and verify the selected NCBI reference before checking inputs')
        source = self.directory / (ref['accession'] + '.fna.gz')
        dest = staged / 'inputs' / source.name
        # The run owns its copy, so moving a job never invalidates its genome path.
        try:
            os.link(source, dest)
        except OSError:
            shutil.copyfile(source, dest)
        return str(dest.relative_to(staged)), state['metadata']
