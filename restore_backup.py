"""Restore a trusted backup into a NEW empty data directory; never touch a live DB."""
import argparse
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path


def restore(archive_path, destination):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('復元先は新しい空のディレクトリを指定してください。')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('重複したパスを含むZIPです。')
        for info in archive.infolist():
            if info.filename not in ('sensor_data.db','manifest.json') and not re.fullmatch(r'photos/[0-9a-f]{32}(-thumb)?\.jpg',info.filename):
                raise ValueError('想定外のファイルが含まれています：'+info.filename)
        if 'sensor_data.db' not in names or 'manifest.json' not in names:
            raise ValueError('バックアップ形式が違います。')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 1:
            raise ValueError('未対応のバックアップ形式です。')
        if sum(i.file_size for i in archive.infolist()) > shutil.disk_usage(destination.parent).free - 10*1024**2:
            raise ValueError('復元に必要な空き容量がありません。')
        with tempfile.TemporaryDirectory(prefix='.restore-',dir=destination.parent) as temp:
            temp=Path(temp)
            for info in archive.infolist():
                target=temp/info.filename
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(info) as source,target.open('wb') as out:
                    shutil.copyfileobj(source,out)
            with sqlite3.connect(temp/'sensor_data.db') as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('データベースの整合性確認に失敗しました。')
                tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'photos' in tables:
                    for filename, thumbnail in db.execute('SELECT filename,thumbnail FROM photos'):
                        if not re.fullmatch(r'[0-9a-f]{32}\.jpg',filename) or not re.fullmatch(r'[0-9a-f]{32}-thumb\.jpg',thumbnail):
                            raise ValueError('写真のファイル名が不正です。')
                        if not (temp/'photos'/filename).is_file() or not (temp/'photos'/thumbnail).is_file():
                            raise ValueError('写真ファイルが不足しています。')
            if destination.exists():
                destination.rmdir()  # Empty only; leaves an existing deployment untouched.
            temp.rename(destination)
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--destination',required=True,type=Path)
    args=parser.parse_args()
    try:
        dest=restore(args.archive,args.destination)
    except (ValueError,OSError,zipfile.BadZipFile,sqlite3.Error) as exc:
        parser.exit(1,str(exc)+'\n')
    print('復元しました：'+str(dest))
    print('DATA_DIR と DB_PATH をこの復元先に変更して再デプロイしてください。')
