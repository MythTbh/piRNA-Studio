"""Portable HTML and ZIP exports from completed runs."""

import io
import json
from pathlib import Path
import zipfile

from engine.report import report
from .store import ROOT


def export(run_dir, rid, result, format_name):
    if format_name == "html":
        return report(result, rid), "text/html; charset=utf-8", "report.html"
    if format_name not in ("zip", "reproduce"):
        raise ValueError("Choose html, zip, or reproduce")
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        if format_name == "zip":
            for item in sorted((run_dir / "outputs").rglob("*")):
                if (
                    item.is_file()
                    and not item.is_symlink()
                    and item != run_dir / "outputs" / "report.html"
                ):
                    bundle.write(item, str(item.relative_to(run_dir / "outputs")))
            if "report.html" not in bundle.namelist():
                bundle.writestr("report.html", report(result, rid))
        else:
            for folder, prefix in [
                (run_dir / "inputs", "inputs"),
                (ROOT / "engine", "engine"),
            ]:
                for item in sorted(folder.rglob("*")):
                    if (
                        item.is_file()
                        and not item.is_symlink()
                        and not (
                            {"__pycache__", "tests", "fixtures", "example"}
                            & set(item.relative_to(folder).parts)
                        )
                    ):
                        bundle.write(item, str(Path(prefix) / item.relative_to(folder)))
            for name in ("requirements.txt", "install_tools.py"):
                source = ROOT / "packaging" / name
                if source.is_file():
                    bundle.write(source, f"packaging/{name}")
            bundle.write(
                run_dir / "outputs" / "environment-lock.json", "environment-lock.json"
            )
            bundle.write(run_dir / "config.json", "config.json")
            bundle.writestr(
                "provenance.json", json.dumps(result["provenance"], indent=2)
            )
            bundle.writestr(
                "RUN.txt",
                "From this extracted directory run:\npython3 engine/pipeline.py config.json outputs\n"
                "Check provenance.json for the original environment and external tools.\n",
            )
    return data.getvalue(), "application/zip", f"{rid}-{format_name}.zip"
