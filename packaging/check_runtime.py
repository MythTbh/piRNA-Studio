"""Verify that the local research environment is ready before opening the app."""
import hashlib
from importlib.metadata import version
import os
from pathlib import Path
import subprocess
import sys


def check():
    if sys.version_info[:2] != (3, 12):
        raise ValueError("The research environment requires Python 3.12")
    root = Path(__file__).resolve().parent.parent
    for requirement in (root / "packaging/requirements.txt").read_text().splitlines():
        if not requirement.strip() or requirement.startswith("#"):
            continue
        package, expected = requirement.split("==")
        if version(package) != expected:
            raise ValueError(f"{package} {expected} is required")
    import cutadapt, pydeseq2, snakemake, fastapi  # noqa: F401
    subprocess.run(["cutadapt", "--version"], check=True, capture_output=True)
    perl = subprocess.check_output(["perl", "-e", "print $^V"], text=True)
    if perl != "v5.32.1":
        raise ValueError("Perl 5.32.1 is required for the tested proTRAC runtime")
    digests = {
        "DUSTER_PL": "ea94869186c15c8dffe6da8077df50d79c71c118a99271d8c3052a6981d40acd",
        "SRNAMAPPER_PL": "6f1e2e60c2df2b2c3648319c8286696f13f75d57bebf412e007103a9cc8c073f",
        "PROTRAC_PL": "4ecd775a345c94f1c0659323504f4f3d8c789cff6d829b22a7d9dd62c6377efd",
    }
    for key, expected in digests.items():
        path = Path(os.environ.get(key, ""))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"{key} needs installation or repair")
        subprocess.run(["perl", "-c", str(path)], check=True, capture_output=True)


if __name__ == "__main__":
    try:
        check()
    except Exception as exc:
        print(f"Research setup needed: {exc}", file=sys.stderr)
        sys.exit(1)
    print("Research tools verified.")
