"""Local, durable resource ledger - the full-flow protection mechanism.

Every resource this MCP creates, reuses, binds or modifies during the Supabase
lifecycle is recorded here so post-deletion cleanup (and any linked operation)
is precise: which resources the flow auto-created, which were reused, which
application they served and whether they have already been cleaned. The ledger
scopes the cleanup hints; live cloud state is always re-verified before any
destructive call - the ledger never substitutes for a guard.

Recording is enabled only when a ledger is explicitly injected (the tool layer
always does); services constructed without one keep their historical behavior.
"""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

KINDS = ('application', 'eip', 'obs_bucket', 'security_group')


def default_path():
    """Mirror the plan store's location policy: beside SUPABASE_STATE_FILE."""
    state = os.getenv('SUPABASE_STATE_FILE', '')
    directory = Path(state).parent if state else Path.home() / '.local/state/huaweicloud-supabase'
    return str(directory / 'resources.sqlite3')


class ResourceLedger:
    def __init__(self, path=None):
        self.path = Path(path or default_path())

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise RuntimeError('Resource ledger must not be a symlink')
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600); os.close(fd)
        if os.name != 'nt': os.chmod(self.path, 0o600)
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS resources ('
                   'kind TEXT NOT NULL, resource_id TEXT NOT NULL, name TEXT,'
                   'auto_created INTEGER NOT NULL DEFAULT 1, application_id TEXT,'
                   'detail TEXT NOT NULL DEFAULT \'{}\','
                   'created_time REAL NOT NULL, updated_time REAL NOT NULL, deleted_time REAL,'
                   'PRIMARY KEY (kind, resource_id))')
        db.commit()
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _merge(self, old, new):
        if not isinstance(old, dict): old = {}
        if isinstance(new, dict): old.update(new)
        return old

    def record_safe(self, kind, resource_id, name=None, auto_created=True,
                    application_id=None, detail=None):
        """Non-fatal recording for post-success hooks: returns a warning string on
        failure (the cloud mutation already succeeded) instead of raising."""
        try:
            self.record(kind, resource_id, name, auto_created, application_id, detail)
            return None
        except Exception as error:  # noqa: BLE001 - advisory persistence must not fail a cloud write
            return '资源记录写入失败（%s）：%s——后续清理请人工核对' % (kind, error)

    def record(self, kind, resource_id, name=None, auto_created=True,
               application_id=None, detail=None):
        if kind not in KINDS:
            raise ValueError('Invalid resource kind: %s' % kind)
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError('resource_id must be a non-empty string')
        now = time.time()
        with self.connect() as db:
            row = db.execute('SELECT detail, created_time FROM resources WHERE kind=? AND resource_id=?',
                             (kind, resource_id)).fetchone()
            merged = self._merge(json.loads(row[0]) if row else {}, detail)
            if row:
                db.execute('UPDATE resources SET name=?, auto_created=?, application_id=?, detail=?,'
                           ' updated_time=?, deleted_time=NULL WHERE kind=? AND resource_id=?',
                           (name, 1 if auto_created else 0, application_id,
                            json.dumps(merged, ensure_ascii=False, sort_keys=True), now,
                            kind, resource_id))
            else:
                db.execute('INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?)',
                           (kind, resource_id, name, 1 if auto_created else 0, application_id,
                            json.dumps(merged, ensure_ascii=False, sort_keys=True), now, now, None))

    def bind(self, kind, resource_id, application_id, name=None, detail=None):
        """Attach an existing resource to an application WITHOUT touching its
        auto_created provenance: insert-if-missing defaults to auto_created=false
        (a reused resource), an existing row keeps its recorded provenance."""
        if kind not in KINDS:
            raise ValueError('Invalid resource kind: %s' % kind)
        now = time.time()
        with self.connect() as db:
            row = db.execute('SELECT auto_created, detail FROM resources WHERE kind=? AND resource_id=?',
                             (kind, resource_id)).fetchone()
            merged = self._merge(json.loads(row[1]) if row else {}, detail)
            if row:
                db.execute('UPDATE resources SET application_id=?, name=COALESCE(?,name), detail=?,'
                           ' updated_time=?, deleted_time=NULL WHERE kind=? AND resource_id=?',
                           (application_id, name, json.dumps(merged, ensure_ascii=False, sort_keys=True),
                            now, kind, resource_id))
            else:
                db.execute('INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?)',
                           (kind, resource_id, name, 0, application_id,
                            json.dumps(merged, ensure_ascii=False, sort_keys=True), now, now, None))

    def bind_safe(self, kind, resource_id, application_id, name=None, detail=None):
        try:
            self.bind(kind, resource_id, application_id, name, detail)
            return None
        except Exception as error:  # noqa: BLE001 - advisory persistence must not fail a cloud write
            return '资源记录写入失败（%s 绑定）：%s——后续清理请人工核对' % (kind, error)

    def application_deleted(self, application_id, detail=None):
        """Mark one application record deleted, merging the deletion context
        (instance cascade choice, retention state) for the cleanup anchor."""
        with self.connect() as db:
            row = db.execute('SELECT detail FROM resources WHERE kind=? AND resource_id=?',
                             ('application', application_id)).fetchone()
            if not row:
                db.execute('INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?)',
                           ('application', application_id, None, 1, None,
                            json.dumps({'deletion': detail or {}}, ensure_ascii=False, sort_keys=True),
                            time.time(), time.time(), time.time()))
                return
            merged = self._merge(json.loads(row[0]), {'deletion': detail or {}})
            db.execute('UPDATE resources SET detail=?, updated_time=?, deleted_time=? '
                       'WHERE kind=? AND resource_id=?',
                       (json.dumps(merged, ensure_ascii=False, sort_keys=True), time.time(),
                        time.time(), 'application', application_id))

    def cleaned(self, kind, resource_id):
        """Mark one resource cleaned so it stops appearing as a residual."""
        with self.connect() as db:
            db.execute('UPDATE resources SET deleted_time=?, updated_time=? '
                       'WHERE kind=? AND resource_id=?',
                       (time.time(), time.time(), kind, resource_id))

    def detach(self, kind, resource_id):
        """Detach one resource from its application binding (full-replacement
        semantics left it out); it stays recorded as an unbound residual."""
        with self.connect() as db:
            db.execute('UPDATE resources SET application_id=NULL, updated_time=? '
                       'WHERE kind=? AND resource_id=?',
                       (time.time(), kind, resource_id))

    def get(self, kind, resource_id):
        with self.connect() as db:
            row = db.execute('SELECT name, auto_created, application_id, detail, created_time,'
                             ' updated_time, deleted_time FROM resources WHERE kind=? AND resource_id=?',
                             (kind, resource_id)).fetchone()
        return self._row(kind, resource_id, row) if row else None

    def rows(self, application_id=None, kind=None, active_only=True):
        query = 'SELECT resource_id, name, auto_created, application_id, detail, created_time,' \
                ' updated_time, deleted_time, kind FROM resources'
        clauses, args = [], []
        if application_id is not None:
            clauses.append('application_id=?'); args.append(application_id)
        if kind is not None:
            clauses.append('kind=?'); args.append(kind)
        if active_only:
            clauses.append('deleted_time IS NULL')
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        with self.connect() as db:
            rows = db.execute(query, args).fetchall()
        return [self._row(row[8], row[0], row[1:]) for row in rows]

    @staticmethod
    def _row(kind, resource_id, row):
        return {'kind': kind, 'resource_id': resource_id, 'name': row[0],
                'auto_created': bool(row[1]), 'application_id': row[2],
                'detail': json.loads(row[3]) if isinstance(row[3], str) else {},
                'created_time': row[4], 'updated_time': row[5], 'deleted_time': row[6]}
