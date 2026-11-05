"""Build a Windows one-folder distribution from source only."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0'


def main():
    if os.name != 'nt':
        raise SystemExit('Build on Windows x64 with Python 3.11+.')
    # Prevent unrelated app runtimes on PATH from shadowing Windows/Qt DLLs (e.g. ICU).
    build_env = dict(os.environ)
    windows = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    build_env['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent,
                                                Path(sys.base_prefix), windows / 'System32', windows]))
    build_env.pop('PYTHONPATH', None)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
                    '--windowed', '--name', 'NeteasePlaylistExporter',
                    '--exclude-module', 'pytest', '--exclude-module', 'Crypto',
                    '--exclude-module', 'tkinter', 'main.py'], cwd=ROOT, check=True, env=build_env)
    target = ROOT / 'dist' / 'NeteasePlaylistExporter'
    for name in ['download_mapping.json', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md']:
        shutil.copyfile(ROOT / name, target / name)
    licenses = target / 'third_party_licenses'
    licenses.mkdir(exist_ok=True)
    for source in (ROOT / 'third_party_licenses').glob('*'):
        if source.is_file():
            shutil.copyfile(source, licenses / source.name)
    manifest = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata['Name']
        # Build environment extras are not distributed or included in the manifest.
        if name.lower() in {'pytest', 'pygments', 'pluggy', 'iniconfig', 'pycryptodome', 'pip', 'setuptools'}:
            continue
        manifest[name] = dist.version
        for entry in dist.files or []:
            parts = str(entry).lower()
            if ('dist-info' in parts and any(x in parts for x in ('license', 'copying', 'notice'))) or 'qtwebengine_resources' in parts and 'license' in parts:
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    dest = licenses / name / str(entry).replace('..', '_')
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, dest)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.exists():
        shutil.copyfile(python_license, licenses / 'PYTHON_LICENSE.txt')
    # Chromium notice is shipped by Qt beside the WebEngine binaries.
    import PySide6
    qt_root = Path(PySide6.__file__).parent
    for source in qt_root.rglob('*'):
        if source.is_file() and source.name.lower() in {'qtwebengineprocess.exe.licenses', 'qtwebengineprocess.licenses', 'qtwebengine.licenses'}:
            shutil.copyfile(source, licenses / source.name)
    manifest['Python'] = sys.version.split()[0]
    (target / 'DEPENDENCIES.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), 'utf-8')
    subprocess.run([str(target / 'NeteasePlaylistExporter.exe'), '--smoke-test'], check=True, timeout=60)
    subprocess.run([str(target / 'NeteasePlaylistExporter.exe'), '--smoke-test', '--browser-smoke-test'],
                   check=True, timeout=60)
    archive = ROOT / 'dist' / f'NeteasePlaylistExporter-v{VERSION}-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in sorted(target.rglob('*')):
            if file.is_file():
                z.write(file, Path(target.name) / file.relative_to(target))
    digest = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
    (ROOT / 'dist' / 'SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n', 'utf-8')
    print(f'BUILT {archive.name} ({archive.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
