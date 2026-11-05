"""Fetch the unmodified Perl scripts from their upstream distributions.

Run with a destination directory. The pinned digests identify the exact versions
used by this build. The application never downloads code during an analysis.
"""

import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile
from urllib.request import urlopen

TOOLS = [
    (
        "TBr2_duster.pl",
        "https://downloads.sourceforge.net/project/ngs-toolbox/TBr2_duster.pl",
        "ea94869186c15c8dffe6da8077df50d79c71c118a99271d8c3052a6981d40acd",
    ),
    (
        "sRNAmapper.pl",
        "https://downloads.sourceforge.net/project/protrac/sRNAmapper.pl",
        "6f1e2e60c2df2b2c3648319c8286696f13f75d57bebf412e007103a9cc8c073f",
    ),
    (
        "proTRAC_2.4.2.pl",
        "https://conda.anaconda.org/bioconda/noarch/protrac-2.4.2-pl5321hdfd78af_3.tar.bz2",
        "86ad3a3379413677f2ee8f9091e7b0f578a86f88ae0c4258a9645e8af6ae13a9",
    ),
]


def main(folder):
    destination = Path(folder)
    destination.mkdir(exist_ok=True, parents=True)
    for name, url, expected in TOOLS:
        with urlopen(url, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Upstream content changed for {name}")
        if url.endswith(".tar.bz2"):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2") as archive:
                data = archive.extractfile("bin/" + name).read()
        path = destination / name
        path.write_bytes(data)
        subprocess.run(["perl", "-c", str(path)], check=True)


if __name__ == "__main__":
    main(sys.argv[1])
