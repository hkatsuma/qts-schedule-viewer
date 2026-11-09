import asyncio
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from src.models import Collection
from src.collectors.cron import CronCollector

UNSUPPORTED = {'power': '電源', 'raid': 'RAIDスクラビング', 'smart': 'S.M.A.R.T.',
               'snapshot': 'スナップショット', 'hbs': 'HBS 3', 'security': 'セキュリティ',
               'updates': '更新', 'qpkg': 'QPKG'}


class CollectionService:
    def __init__(self, collector: CronCollector, interval: int = 300, annotations=None):
        self.collector, self.interval = collector, interval
        self.results: dict[str, Collection] = {}
        self.lock = asyncio.Lock()
        self.pending: asyncio.Task | None = None
        self.annotations = annotations
        self.annotation_error = False

    async def refresh(self) -> None:
        if self.lock.locked():
            return
        async with self.lock:
            # Never launch repeated threads when a timed-out filesystem read is
            # still blocked. The same pending collection is checked next time.
            if self.pending is None:
                now = datetime.now(ZoneInfo(self.collector.timezone))
                self.pending = asyncio.create_task(asyncio.to_thread(self.collector.collect, now))
            now = datetime.now(ZoneInfo(self.collector.timezone))
            try:
                result = await asyncio.wait_for(asyncio.shield(self.pending), timeout=5)
                self.pending = None
            except TimeoutError:
                result = Collection(collector='cron', status='unavailable', message='収集がタイムアウトしました', attempted_at=now)
            except Exception:
                self.pending = None
                result = Collection(collector='cron', status='parse_error', message='収集中にエラーが発生しました', attempted_at=now)
            previous = self.results.get('cron')
            if previous:
                result.previous_status = previous.status
                result.last_success_at = result.last_success_at or previous.last_success_at
                if result.status in ('unavailable', 'permission_denied', 'parse_error'):
                    result.tasks = previous.tasks
                    result.stale = bool(previous.tasks)
            self.results['cron'] = result
            if self.annotations:
                try:
                    migrations = {}
                    for task in result.tasks:
                        if task.definition_id and task._legacy_definition_id:
                            migrations.setdefault(task.definition_id, set()).add(task._legacy_definition_id)
                    await asyncio.to_thread(self.annotations.observe,
                        {t.definition_id for t in result.tasks if t.definition_id},
                        result.status, result.attempted_at.isoformat(), stale=result.stale, identity_migrations=migrations)
                    self.annotation_error = False
                except (sqlite3.Error, OSError):
                    self.annotation_error = True
            for key, label in UNSUPPORTED.items():
                self.results[key] = Collection(collector=key, status='unsupported',
                    message=f'{label}: 実機調査待ち（未インストール・タスクなしとは判定していません）', attempted_at=now)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            await self.refresh()
