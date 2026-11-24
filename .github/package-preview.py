from pathlib import Path
import hashlib
import shutil
import subprocess
from zipfile import ZipFile

root = Path('/tmp/sdc-preview5')
name = 'SDC-BULKVIDDL-Windows-x64.zip'
repo = '.'
rev = 'b2f978a381d2948ae521c219323c043d0c918a93'
def from_commit(path):
    return subprocess.check_output(['git', '-C', repo, 'show', f'{rev}:{path}'])

changed = ('vbd.py', 'index.html', 'README.txt')
with ZipFile(root/'base'/name) as old, ZipFile(root/'asset'/name, 'w') as new:
    names = old.namelist()
    launcher, = [n for n in names if n.endswith('Video Bulk Downloader.exe')]
    prefix = launcher[:-len('Video Bulk Downloader.exe')]
    replacements = {prefix + n: from_commit(n) for n in changed}
    assert replacements.keys() <= set(names)
    template = prefix + 'Queue Template.xlsx'
    template_data = from_commit('Queue Template.xlsx')
    assert template not in names
    for entry in old.infolist():
        if entry.filename in replacements:
            new.writestr(entry, replacements[entry.filename])
        else:
            with old.open(entry) as src, new.open(entry, 'w') as dst:
                shutil.copyfileobj(src, dst)
    new.writestr(template, template_data)

with ZipFile(root/'base'/name) as old, ZipFile(root/'asset'/name) as new:
    assert new.testzip() is None
    assert new.namelist() == old.namelist() + [template]
    assert new.read(template) == template_data
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
