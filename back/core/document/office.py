"""LibreOffice PDF export shared by document preparation and file conversion."""

from pathlib import Path
import shutil
import subprocess


def office_pdf(path: Path, suffix: str, directory: Path, *, preview_only: bool = False) -> Path:
    if shutil.which("soffice") is None:
        raise ValueError("LibreOffice is unavailable")
    office = directory / ("source" + suffix)
    shutil.copyfile(path, office)
    profile = (directory / "office-profile").absolute().as_uri()
    profile_dir = directory / "office-profile" / "user"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "registrymodifications.xcu").write_text(
        '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
        '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
        '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
        '<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>'
        '</item></oor:items>', encoding="utf-8")
    source = directory / "source.pdf"
    if not source.is_file():
        output_format = "pdf"
        if preview_only:
            pdf_filter = (
                "calc_pdf_Export" if suffix in {".xls", ".xlsx", ".ods"}
                else "impress_pdf_Export" if suffix in {".ppt", ".pptx", ".odp"}
                else "draw_pdf_Export" if suffix == ".odg" else "writer_pdf_Export"
            )
            output_format = f'pdf:{pdf_filter}:{{"PageRange":{{"type":"string","value":"1"}}}}'
        result = subprocess.run(
            ["soffice", f"-env:UserInstallation={profile}", "--headless", "--nologo", "--nodefault", "--norestore",
             "--convert-to", output_format, "--outdir", str(directory), str(office)],
            timeout=90 if preview_only else 180, capture_output=True, check=False,
        )
        if result.returncode:
            raise ValueError("Document converter failed")
    if not source.is_file():
        raise ValueError("Office converter produced no PDF")
    return source
