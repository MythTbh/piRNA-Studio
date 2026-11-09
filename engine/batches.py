"""Bound native-tool indexes and retain content-verified completed batches."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from itertools import islice


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def batch_size():
    value = int(os.environ.get('PIRNA_BATCH_READS', '250000'))
    if not 1 <= value <= 1000000:
        raise ValueError('PIRNA_BATCH_READS must be between 1 and 1000000 distinct sequences')
    return value


def prepare(counts, root, context):
    root.mkdir(parents=True, exist_ok=True)
    iterator = iter(counts.items())
    index = 0
    while True:
        entries = list(islice(iterator, batch_size()))
        if not entries:
            return
        folder = root / f'{index:06d}'
        folder.mkdir(exist_ok=True)
        path = folder / 'reads.fa'
        temporary = folder / 'reads.tmp'
        with temporary.open('w') as stream:
            for seq, count in entries:
                stream.write(f'>{count}\n{seq}\n')
        key = hashlib.sha256((context + digest(temporary)).encode()).hexdigest()
        temporary.replace(path)
        yield folder, key
        index += 1


def valid(folder, key, outputs):
    try:
        record = json.loads((folder / 'complete.json').read_text())
        return record['key'] == key and all(record['outputs'][name] == digest(folder / name) for name in outputs)
    except (OSError, ValueError, KeyError):
        return False


def finish(folder, key, outputs):
    record = {'key': key, 'outputs': {name: digest(folder / name) for name in outputs}}
    temporary = folder / 'complete.tmp'
    temporary.write_text(json.dumps(record))
    temporary.replace(folder / 'complete.json')


def dust(counts, folder, invoke):
    tool = Path(os.environ['DUSTER_PL']).resolve()
    context = 'duster-v1:' + digest(tool)
    outputs = ['reads.fa.no-dust', 'reads.fa.dust']
    def work(item):
        part, key = item
        if not valid(part, key, outputs):
            (part / 'complete.json').unlink(missing_ok=True)
            invoke(['perl', str(tool), '-i', 'reads.fa'], part)
            finish(part, key, outputs)
        return part
    result = {}
    # Submit at most two batches, rather than materializing all input or futures.
    items = iter(prepare(counts, folder / 'dust-batches', context))
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = []
        for _ in range(2):
            item = next(items, None)
            if item is not None:
                pending.append(pool.submit(work, item))
        while pending:
            part = pending.pop(0).result()
            with (part / outputs[0]).open() as stream:
                for header in stream:
                    if not header.startswith('>'):
                        raise ValueError('Invalid Duster FASTA output')
                    result[next(stream).strip().upper()] = int(header[1:].strip())
            print(f'Duster batch {part.name} complete', flush=True)
            item = next(items, None)
            if item is not None:
                pending.append(pool.submit(work, item))
    return result


def map_reads(counts, genome, folder, invoke):
    tool = Path(os.environ['SRNAMAPPER_PL']).resolve()
    genome = Path(genome).resolve()
    context = 'srnamapper-best-eland-v1:' + digest(tool) + digest(genome)
    # SQLite sorts on disk; concatenating chromosome-sorted batches is not globally sorted.
    database = folder / 'merge.sqlite3'
    database.unlink(missing_ok=True)
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA temp_store=FILE')
        db.execute('PRAGMA cache_size=-16384')
        db.execute('CREATE TABLE hits(chrom TEXT, position INTEGER, line TEXT)')
        for part, key in prepare(counts, folder / 'map-batches', context):
            if not valid(part, key, ['aligned.map']):
                (part / 'complete.json').unlink(missing_ok=True)
                invoke(['perl', str(tool), '-input', 'reads.fa', '-genome', str(genome),
                        '-alignments', 'best', '-format', 'eland', '-output', 'aligned.map'], part)
                finish(part, key, ['aligned.map'])
            def records():
                with (part / 'aligned.map').open() as stream:
                    for line in stream:
                        if not line.strip():
                            continue
                        fields = line.rstrip().split()
                        if len(fields) < 7 or fields[4].upper() not in counts or fields[6] not in {'+', '-'}:
                            raise ValueError('Invalid mapper output')
                        pos = int(fields[1])
                        if pos < 1:
                            raise ValueError('Invalid mapper position')
                        yield fields[0], pos, line.rstrip() + '\n'
            db.executemany('INSERT INTO hits VALUES(?,?,?)', records())
            db.commit()
            print(f'Mapping batch {part.name} complete', flush=True)
        temporary = folder / 'aligned.map.tmp'
        with temporary.open('w') as stream:
            for (line,) in db.execute('SELECT line FROM hits ORDER BY chrom,position,line'):
                stream.write(line)
        temporary.replace(folder / 'aligned.map')
    database.unlink()
