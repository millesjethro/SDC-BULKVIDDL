from pathlib import Path
import hashlib
import shutil
import subprocess
from zipfile import ZipFile

root = Path('/tmp/sdc-preview4')
name = 'SDC-BULKVIDDL-Windows-x64.zip'
repo = '.'
rev = 'e1b7cc1c1aa618de64989d22e7e273af93fbe991'
def from_commit(path):
    return subprocess.check_output(['git', '-C', repo, 'show', f'{rev}:{path}'])

changed = ('vbd.py', 'index.html', 'README.txt')
with ZipFile(root/'base'/name) as old, ZipFile(root/'asset'/name, 'w') as new:
    names = old.namelist()
    launcher, = [n for n in names if n.endswith('Video Bulk Downloader.exe')]
    prefix = launcher[:-len('Video Bulk Downloader.exe')]
    replacements = {prefix + n: from_commit(n) for n in changed}
    assert replacements.keys() <= set(names)
    for entry in old.infolist():
        if entry.filename in replacements:
            new.writestr(entry, replacements[entry.filename])
        else:
            with old.open(entry) as src, new.open(entry, 'w') as dst:
                shutil.copyfileobj(src, dst)

with ZipFile(root/'base'/name) as old, ZipFile(root/'asset'/name) as new:
    assert new.testzip() is None
    assert old.namelist() == new.namelist()
    for key, data in replacements.items():
        assert new.read(key) == data
    for entry in old.infolist():
        if entry.filename not in replacements:
            assert new.getinfo(entry.filename).CRC == entry.CRC
    assert any(n.endswith('runtime/pythonw.exe') for n in names)
    assert any(n.endswith('/manifest.json') and 'Chrome Extension' in n for n in names)
    assert any(n.endswith('yt-dlp.exe') for n in names)
    assert any(n.endswith('ffmpeg.exe') for n in names)
    compile(new.read(prefix+'vbd.py'), 'vbd.py', 'exec')

with (root/'asset'/name).open('rb') as f:
    print(f'{rev}  SHA-256 {hashlib.file_digest(f, "sha256").hexdigest()}')
