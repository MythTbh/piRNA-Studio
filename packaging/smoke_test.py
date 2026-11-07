"""Check HTTP startup, real job execution and exports on the installed runtime."""
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import inputs
from server.test_service import form


def main():
    with tempfile.TemporaryDirectory(prefix='piRNA HTTP smoke ') as tmp:
        process = subprocess.Popen(
            [sys.executable, '-u', '-m', 'server', '--port', '0', '--data', tmp],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        lines = queue.Queue()
        def consume():
            for line in process.stdout:
                lines.put(line)
        threading.Thread(target=consume, daemon=True).start()
        try:
            ready = lines.get(timeout=45)
            assert 'is ready at ' in ready, ready
            base = ready.strip().split('is ready at ')[1]
            with urlopen(base + '/api/health', timeout=30) as response:
                assert json.load(response)['max_upload_bytes'] == 4 * 1024 ** 3
            with urlopen(base + '/', timeout=30) as response:
                assert b'piRNA Studio' in response.read()
            config = inputs.load_config(ROOT / 'engine/example/config.json')
            config['samples'] = [config['samples'][0], config['samples'][3]]
            config['params']['backend'] = 'portable'
            config['params']['de_method'] = 'auto'
            # form() uses text input; convert fixtures into plain FASTQ for this test.
            import gzip
            uploaded = []
            for sample in config['samples']:
                path = Path(sample['fastq_path'])
                with gzip.open(path, 'rt') as stream:
                    text = stream.read()
                name = path.stem
                sample['fastq_path'] = name
                uploaded.append((name, text))
            for key in ['genome', 'reference']:
                path = Path(config[key]); config[key] = path.name
                uploaded.append((path.name, path.read_text()))
            config['ncrna'] = {}
            headers, body = form(config, uploaded)
            request = Request(base + '/api/runs', data=body, headers=headers)
            with urlopen(request, timeout=30) as response:
                rid = json.load(response)['run_id']
            for _ in range(120):
                with urlopen(base + f'/api/runs/{rid}/status', timeout=10) as response:
                    status = json.load(response)
                if status['status'] in {'failed', 'completed', 'cancelled'}:
                    break
                time.sleep(0.25)
            assert status['status'] == 'completed', status
            with urlopen(base + f'/api/runs/{rid}/results', timeout=30) as response:
                result = json.load(response)
            assert result['clusters'] and result['de']
            assert all(row['pvalue'] is None for row in result['de'])
            with urlopen(base + f'/api/runs/{rid}/export?format=zip', timeout=30) as response:
                with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                    assert archive.testzip() is None
            print('PASS HTTP startup, upload, analysis and ZIP export on', sys.platform)
        finally:
            process.terminate()
            process.wait(timeout=15)
            process.stdout.close()


if __name__ == '__main__':
    main()
