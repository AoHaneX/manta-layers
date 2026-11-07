"""ReefKit release helper: the Windows release convention read by RiftKit Launcher (convention 1).

Keep this file identical in every ReefKit application repository: what differs between
applications lives in ``packaging/release.json`` next to it. Standard library only, Python 3.11+.

    python packaging/reefkit_release.py version [--tag vX.Y.Z]
    python packaging/reefkit_release.py finalize --dir release [--tag vX.Y.Z] [--allow-missing-installer]
    python packaging/reefkit_release.py verify --dir release
    python packaging/reefkit_release.py smoke --dir release [--seconds 8] [--env NAME=VALUE] [--arg=--opt]

Convention 1 (one GitHub release per version, Windows x64 only):

    tag          vMAJOR.MINOR.PATCH, equal to the version declared in the code
    portable     <AppName>-vX.Y.Z-win64.zip, the executable at the root of the archive
    installer    <AppName>-vX.Y.Z-setup.exe (Inno Setup), when the application has one
    checksums    SHA256SUMS.txt, "<sha256>  <file name>" lines, for the two files above
    notes        release-notes.md, structured Markdown used as the body of the GitHub release
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

CONVENTION = 1
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG = HERE / "release.json"
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SUMS_NAME = "SHA256SUMS.txt"
NOTES_NAME = "release-notes.md"
SILENT_INSTALL = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER"


class ReleaseError(Exception):
    """A release that does not follow the convention; the message says what to fix."""


@dataclass(frozen=True)
class Config:
    id: str
    app_name: str
    display_name: str
    repository: str
    executable: str
    installer: bool
    version_sources: list[dict]
    changelog: str | None
    user_data: list[dict]
    notes: list[str]

    @classmethod
    def load(cls, path: Path = CONFIG) -> Config:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("convention") != CONVENTION:
            raise ReleaseError(f"{path.name}: convention {CONVENTION} attendue.")
        config = cls(
            id=data["id"],
            app_name=data["appName"],
            display_name=data["displayName"],
            repository=data["repository"],
            executable=data["executable"],
            installer=bool(data["installer"]),
            version_sources=data["versionSources"],
            changelog=data.get("changelog"),
            user_data=list(data.get("userData", [])),
            notes=list(data.get("notes", [])),
        )
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", config.app_name):
            raise ReleaseError("appName : lettres et chiffres seulement, sans espace ni tiret.")
        executable = config.executable
        if not executable.lower().endswith(".exe") or any(sep in executable for sep in "/\\"):
            raise ReleaseError("executable : nom d'un fichier .exe placé à la racine de l'archive.")
        return config

    def portable(self, version: str) -> str:
        return f"{self.app_name}-v{version}-win64.zip"

    def setup(self, version: str) -> str:
        return f"{self.app_name}-v{version}-setup.exe"


def read_version(config: Config, tag: str | None = None) -> str:
    """The version declared by every source of the code; all must agree, and match the tag if given."""
    found: dict[str, str] = {}
    for source in config.version_sources:
        text = (ROOT / source["file"]).read_text(encoding="utf-8")
        match = re.search(source["pattern"], text, re.MULTILINE)
        if not match:
            raise ReleaseError(f"Version introuvable dans {source['file']}.")
        found[source["file"]] = match.group(1)
    versions = set(found.values())
    if len(versions) != 1:
        detail = ", ".join(f"{name} = {value}" for name, value in found.items())
        raise ReleaseError(f"Les sources de version ne concordent pas : {detail}.")
    version = versions.pop()
    if not VERSION_RE.match(version):
        raise ReleaseError(f"La version {version} n'est pas au format MAJOR.MINOR.PATCH.")
    if tag and tag != f"v{version}":
        raise ReleaseError(f"Le tag {tag} ne correspond pas à la version du code (v{version}).")
    return version


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_portable(config: Config, archive: Path) -> None:
    """The launcher extracts the archive as is and starts <executable> from its root."""
    if not archive.is_file():
        raise ReleaseError(f"Archive portable absente : {archive.name}.")
    with zipfile.ZipFile(archive) as bundle:
        # orig_filename: ZipInfo turns "\\" into "/" on Windows, which would hide a non-portable name.
        names = [entry.orig_filename for entry in bundle.infolist()]
        broken = bundle.testzip()
    if broken:
        raise ReleaseError(f"{archive.name} est corrompue ({broken}).")
    if config.executable not in names:
        raise ReleaseError(f"{config.executable} doit se trouver à la racine de {archive.name}.")
    for name in names:
        parts = PurePosixPath(name).parts
        if "\\" in name or name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
            raise ReleaseError(f"Chemin non portable dans {archive.name} : {name!r}.")


def changelog_section(config: Config, version: str) -> str | None:
    """The "## <version>" section of the changelog, without its heading."""
    if not config.changelog:
        return None
    path = ROOT / config.changelog.format(version=version)
    if not path.is_file():
        return None
    heading = re.compile(rf"^##\s+\[?v?{re.escape(version)}\]?(\s|$)")
    lines, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            if inside:
                break
            inside = bool(heading.match(line))
            continue
        if inside:
            lines.append(line)
    text = "\n".join(lines).strip()
    return text or None


def french_size(path: Path) -> str:
    return f"{path.stat().st_size / (1024 * 1024):.1f} Mo".replace(".", ",")


def release_notes(config: Config, version: str, files: list[Path]) -> str:
    name = f"{config.display_name} v{version}"
    portable, setup = config.portable(version), config.setup(version)
    changes = changelog_section(config, version) or "_À compléter avant la publication._"
    usage = {
        setup: "Installeur : menu Démarrer, mises à jour, désinstallation",
        portable: f"Version portable : extraire, puis lancer `{config.executable}`",
    }
    rows = [
        f"| `{path.name}` | {usage[path.name]} | {french_size(path)} | `{sha256(path)}` |"
        for path in sorted(files, key=lambda item: item.name != setup)
    ]
    rows.append(f"| `{SUMS_NAME}` | Empreintes SHA-256 des fichiers ci-dessus | | |")
    install = []
    if any(path.name == setup for path in files):
        install.append(
            f"- **Installeur** : lancez `{setup}`. Il met à jour une installation existante, au même "
            f"endroit. Installation sans interface : `{setup} {SILENT_INSTALL}`."
        )
    install.append(
        f"- **Portable** : extrayez toute l'archive dans un dossier vide, puis lancez "
        f"`{config.executable}` ; gardez le dossier `_internal` à côté. Pour mettre à jour, remplacez "
        "le dossier."
    )
    data = [f"- {entry['content']} : `{entry['path']}`" for entry in config.user_data]
    data = data or ["- Aucune donnée en dehors du dossier de l'application."]
    remarks = [
        "- Windows 10 ou 11, 64 bits (x64). Python n'est pas nécessaire.",
        (
            "- Les exécutables ne sont pas signés : si SmartScreen s'affiche, choisissez « Informations "
            "complémentaires », puis « Exécuter quand même »."
        ),
        *[f"- {line}" for line in config.notes],
    ]
    return "\n".join(
        [
            f"# {name}",
            "",
            (
                f"{name} pour Windows 10 et 11, 64 bits. Les distributions sont autonomes : Python et les "
                "bibliothèques nécessaires sont inclus."
            ),
            "",
            "## Nouveautés",
            "",
            changes,
            "",
            "## Téléchargements",
            "",
            "| Fichier | Usage | Taille | SHA-256 |",
            "| --- | --- | --- | --- |",
            *rows,
            "",
            "## Installation",
            "",
            *install,
            "",
            "## Données utilisateur",
            "",
            "Les mises à jour et la désinstallation conservent les données de l'utilisateur :",
            "",
            *data,
            "",
            "## Vérifier l'intégrité",
            "",
            "```powershell",
            f"Get-FileHash .\\{portable} -Algorithm SHA256",
            "```",
            "",
            f"L'empreinte affichée doit être celle de `{SUMS_NAME}`.",
            "",
            "## Configuration et remarques",
            "",
            *remarks,
            "",
        ]
    )


def finalize(config: Config, directory: Path, tag: str | None, allow_missing_installer: bool) -> list[str]:
    version = read_version(config, tag)
    portable = directory / config.portable(version)
    check_portable(config, portable)
    files = [portable]
    setup = directory / config.setup(version)
    if config.installer:
        if setup.is_file():
            files.append(setup)
        elif not allow_missing_installer:
            raise ReleaseError(f"Installeur absent : {setup.name}.")
    elif setup.exists():
        raise ReleaseError(f"{setup.name} existe alors que release.json déclare installer: false.")
    lines = [f"{sha256(path)}  {path.name}" for path in sorted(files, key=lambda item: item.name)]
    (directory / SUMS_NAME).write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    notes = release_notes(config, version, files)
    (directory / NOTES_NAME).write_text(notes, encoding="utf-8", newline="\n")
    return lines


def verify(config: Config, directory: Path) -> list[str]:
    """Check SHA256SUMS.txt: well-formed, standard names of a single version, matching files."""
    sums = directory / SUMS_NAME
    if not sums.is_file():
        raise ReleaseError(f"{SUMS_NAME} absent de {directory}.")
    entries: dict[str, str] = {}
    for number, line in enumerate(sums.read_text(encoding="ascii").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](\S+)", line)
        if not match:
            raise ReleaseError(f"{SUMS_NAME}, ligne {number} mal formée : {line!r}.")
        entries[match.group(2)] = match.group(1)
    pattern = re.compile(rf"^{re.escape(config.app_name)}-v(\d+\.\d+\.\d+)-(win64\.zip|setup\.exe)$")
    versions = set()
    for name in entries:
        match = pattern.match(name)
        if not match:
            raise ReleaseError(f"Nom hors convention dans {SUMS_NAME} : {name}.")
        versions.add(match.group(1))
    if len(versions) != 1:
        raise ReleaseError(f"{SUMS_NAME} doit décrire une seule version (trouvé : {sorted(versions)}).")
    version = versions.pop()
    if config.portable(version) not in entries:
        raise ReleaseError(f"{config.portable(version)} manque dans {SUMS_NAME}.")
    report = []
    for name, expected in sorted(entries.items()):
        actual = sha256(directory / name)
        if actual != expected:
            raise ReleaseError(f"Empreinte SHA-256 différente pour {name}.")
        report.append(f"OK  {name}")
    return report


def smoke(config: Config, directory: Path, seconds: float, env_pairs: list[str], app_args: list[str]) -> str:
    """Start the executable of the extracted archive as a user would, without Python on the PATH.

    Without arguments, the application must still be running after ``seconds``. With arguments
    (a self-test), it must exit with code 0 within ``seconds``; ``{report}`` in an argument is
    replaced by a file path whose content is returned. The user's profile folders are redirected
    to a temporary sandbox so that the real preferences, logs and projects are never touched.
    """
    version = read_version(config)
    archive = directory / config.portable(version)
    check_portable(config, archive)
    with tempfile.TemporaryDirectory(prefix="riftkit-smoke-", ignore_cleanup_errors=True) as temporary:
        base = Path(temporary)
        target = base / "Dossier d'essai é" / config.app_name
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
        profile = base / "profile"
        for folder in ("Local", "Roaming", "Temp"):
            (profile / folder).mkdir(parents=True)
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
        env.update(
            PATH=os.pathsep.join([rf"{system_root}\System32", system_root, rf"{system_root}\System32\Wbem"]),
            LOCALAPPDATA=str(profile / "Local"),
            APPDATA=str(profile / "Roaming"),
            TEMP=str(profile / "Temp"),
            TMP=str(profile / "Temp"),
            QT_QPA_PLATFORM=env.get("QT_QPA_PLATFORM", "offscreen"),
        )
        for pair in env_pairs:
            key, _, value = pair.partition("=")
            env[key] = value
        report = profile / "report.txt"
        arguments = [arg.replace("{report}", str(report)) for arg in app_args]
        command = [str(target / config.executable), *arguments]
        process = subprocess.Popen(command, cwd=profile, env=env)
        try:
            code = process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            if not app_args:
                return f"{config.executable} tourne encore après {seconds:g} s, lancé depuis l'archive."
            code = None
        output = report.read_text(encoding="utf-8", errors="replace") if report.is_file() else ""
        if code is None:
            raise ReleaseError(f"{config.executable} {' '.join(app_args)} n'a pas fini en {seconds:g} s.")
        if not app_args:
            raise ReleaseError(f"{config.executable} s'est arrêté au démarrage (code {code}).\n{output}")
        if code != 0:
            raise ReleaseError(f"{config.executable} {' '.join(app_args)} a échoué (code {code}).\n{output}")
        return output or f"{config.executable} {' '.join(app_args)} : code 0."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    version = commands.add_parser("version", help="print the version, checked against the tag")
    version.add_argument("--tag", default=None)
    final = commands.add_parser("finalize", help="check the archive, write SHA256SUMS.txt and the notes")
    final.add_argument("--dir", type=Path, required=True)
    final.add_argument("--tag", default=None)
    final.add_argument("--allow-missing-installer", action="store_true")
    check = commands.add_parser("verify", help="check SHA256SUMS.txt against the files")
    check.add_argument("--dir", type=Path, required=True)
    run = commands.add_parser("smoke", help="start the executable from the extracted archive")
    run.add_argument("--dir", type=Path, required=True)
    run.add_argument("--seconds", type=float, default=8)
    run.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    # "--arg=--check": Windows PowerShell drops a bare "--" passed to a native program.
    run.add_argument("--arg", action="append", default=[], dest="app_args", metavar="ARGUMENT")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        config = Config.load()
        if args.command == "version":
            print(read_version(config, args.tag or None))
        elif args.command == "finalize":
            for line in finalize(config, args.dir, args.tag or None, args.allow_missing_installer):
                print(line)
        elif args.command == "verify":
            print("\n".join(verify(config, args.dir)))
        else:
            print(smoke(config, args.dir, args.seconds, args.env, args.app_args))
    except (ReleaseError, OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        print(f"ERREUR : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
