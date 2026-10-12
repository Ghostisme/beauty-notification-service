import zipfile

import pytest

from manage import backup
from toolbox.db import Database
from toolbox.engine import Engine
from .conftest import delivery, lead


def test_live_backup_restores_database_and_encrypted_credentials(db,engine,tmp_path):
    db.set_secret('douyin_secret','fixture-backup-secret')
    engine.ingest_event(lead())
    archive=backup(db,tmp_path/'backups')
    restored=tmp_path/'restored';restored.mkdir()
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist())=={'tool.db','.master-key'}
        z.extractall(restored)
    replacement=Database(restored)
    assert replacement.secret('douyin_secret')=='fixture-backup-secret'
    assert replacement.one('SELECT COUNT(*) AS n FROM messages')['n']==1
    assert replacement.one('PRAGMA integrity_check')['integrity_check']=='ok'


def test_sender_key_does_not_reuse_after_restoring_older_database(db,engine,tmp_path):
    engine.ingest_event(lead(record='before-backup'))
    delivery(db)
    archive=backup(db,tmp_path/'backups')
    engine.ingest_event(lead(record='after-backup-original'))
    first=engine.claim('w');second=engine.claim('w')
    restored=tmp_path/'restored';restored.mkdir()
    with zipfile.ZipFile(archive) as z:z.extractall(restored)
    another_db=Database(restored);another=Engine(another_db)
    another.ingest_event(lead(record='after-backup-different'))
    restored_first=another.claim('w');restored_second=another.claim('w')
    assert first['idempotency_key']==restored_first['idempotency_key']
    assert second['id']==restored_second['id']
    assert second['idempotency_key']!=restored_second['idempotency_key']


def test_missing_key_does_not_silently_replace_existing_encryption_key(db):
    key=db.directory/'.master-key'
    key.unlink()
    with pytest.raises(RuntimeError,match='密钥缺失'):Database(db.directory)
    assert not key.exists()
