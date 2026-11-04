import asyncio
import csv
import io
import os
import sqlite3
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from src.collectors.cron import CronCollector
from src.models import Task, Tag
from src.annotation_api import annotation_router
from src.services.annotations import AnnotationStore, AnnotationError
from src.services.collection import CollectionService
from src.services.access import IPAllowlist
from src.services.schedules import occurrences, next_runs, month_summary

WEB = Path(__file__).parent / 'web'
Frequency = Literal['all', 'nonfrequent', 'frequent']
FREQUENT_RUNS_PER_DAY = 24


def frequency_matches(task: Task, frequency: Frequency) -> bool:
    frequent = task.runs_per_active_day is not None and task.runs_per_active_day >= FREQUENT_RUNS_PER_DAY
    return frequency == 'all' or (frequency == 'frequent' and frequent) or (frequency == 'nonfrequent' and not frequent)


def create_app(path: Path | None = None, timezone: str | None = None,
               allowed_proxy_ips: str | None = None, db_path: Path | None = None) -> FastAPI:
    zone = timezone or os.getenv('QSV_TIMEZONE', 'Asia/Tokyo')
    ZoneInfo(zone)  # Fail clearly at startup on a misconfigured timezone.
    allowlist = IPAllowlist(allowed_proxy_ips if allowed_proxy_ips is not None
                           else os.getenv('QSV_ALLOWED_PROXY_IPS', ''))
    store = AnnotationStore(db_path if db_path is not None else Path(os.getenv('QSV_DB_PATH', '/data/qsv.sqlite3')))
    service = CollectionService(CronCollector(path or Path(os.getenv('QSV_CRONTAB_PATH', '/host/crontab')), zone),
                                max(30, int(os.getenv('QSV_REFRESH_SECONDS', '300'))), annotations=store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await asyncio.to_thread(store.initialize)
        except (sqlite3.Error, OSError):
            raise RuntimeError('注釈DBを開けません。ローカル永続ボリュームと書き込み権限を確認してください') from None
        await service.refresh()
        if service.annotation_error:
            raise RuntimeError('注釈DBの初期更新に失敗しました')
        background = asyncio.create_task(service.run())
        yield
        background.cancel()
        with suppress(asyncio.CancelledError):
            await background

    app = FastAPI(title='QTS Schedule Viewer', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.collection = service
    app.state.annotations = store
    app.include_router(annotation_router(store, service))

    @app.exception_handler(AnnotationError)
    async def annotation_error(request, error):
        return JSONResponse({'detail': error.message}, status_code=error.status)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        return JSONResponse({'detail': '注釈DBを利用できません。保存領域を確認してください'}, status_code=503)


    @app.middleware('http')
    async def headers(request: Request, call_next):
        peer = request.client.host if request.client else None
        if request.url.path == '/healthz' and peer in ('127.0.0.1', '::1', '::ffff:127.0.0.1'):
            # Loopback exemption is limited to container-local liveness checks.
            response = await call_next(request)
        elif not allowlist.permits(peer):
            response = Response('Forbidden', status_code=403, media_type='text/plain')
        else:
            origin = request.headers.get('origin')
            unsafe = request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
            try:
                cross_origin = bool(origin) and (urlsplit(origin).scheme not in ('http', 'https') or urlsplit(origin).netloc != request.url.netloc)
            except ValueError:
                cross_origin = True
            if unsafe and (cross_origin or request.headers.get('sec-fetch-site') == 'cross-site'):
                response = JSONResponse({'detail': '異なるサイトからの操作はできません'}, status_code=403)
            elif unsafe and request.url.path.startswith(('/api/tags', '/api/annotations')):
                if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                    response = JSONResponse({'detail': 'JSON形式で送信してください'}, status_code=415)
                else:
                    body = bytearray()
                    oversized = False
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > 16384:
                            oversized = True
                            break
                        body.extend(chunk)
                    if oversized:
                        response = JSONResponse({'detail': 'リクエストが大きすぎます'}, status_code=413)
                    else:
                        request._body = bytes(body)
                        response = await call_next(request)
            else:
                response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def decorated(stored, snapshot):
        task = stored.model_copy(deep=True)
        task.original_name = stored.name
        annotation = snapshot['annotations'].get(task.definition_id)
        if annotation:
            task.display_name = annotation['display_name']
            task.name = task.display_name or stored.name
            task.tags = [Tag(**tag) for tag in annotation['tags']]
            task.annotation_version = annotation['version']
        return task

    def tasks(q: str = '', category: str = '', provider: str = '', enabled: str = '', frequency: Frequency = 'all',
              tag: list[int] = (), tag_match: Literal['any', 'all'] = 'any', snapshot=None):
        if service.annotation_error:
            raise HTTPException(503, '注釈の収集状態を確認できません。再取得してください')
        snapshot = snapshot if snapshot is not None else store.snapshot()
        result = []
        for collection in service.results.values():
            for stored in collection.tasks:
                task = decorated(stored, snapshot)
                selected, assigned = set(tag), {t.id for t in task.tags}
                if selected and not (selected <= assigned if tag_match == 'all' else selected & assigned):
                    continue
                if not frequency_matches(task, frequency):
                    continue
                if task.enabled and task.collection_status == 'ok':
                    task.next_runs = next_runs(task.schedule.expression, datetime.now(ZoneInfo(zone)))
                if category and task.category != category or provider and task.provider != provider:
                    continue
                if enabled and {'true': True, 'false': False, 'unknown': None}.get(enabled) != task.enabled:
                    continue
                if q.casefold() not in task.model_dump_json().casefold():
                    continue
                result.append(task)
        return sorted(result, key=lambda t: t.next_runs[0].timestamp() if t.next_runs else float('inf'))

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    @app.get('/api/schedules')
    def schedules(q: str = Query('', max_length=200), category: str = '', provider: str = '', enabled: str = '', frequency: Frequency = 'all', tag: list[int] = Query(default=[], max_length=200), tag_match: Literal['any', 'all'] = 'any'):
        snapshot = store.snapshot()
        matching = tasks(q, category, provider, enabled, tag=tag, tag_match=tag_match, snapshot=snapshot)
        visible = [task for task in matching if frequency_matches(task, frequency)]
        return {'timezone': zone, 'tasks': visible,
                'hidden_by_frequency': len(matching) - len(visible),
                'frequent_runs_per_day': FREQUENT_RUNS_PER_DAY,
                'tags': snapshot['tags'],
                'collections': [c.model_copy(update={'tasks': [decorated(t, snapshot) for t in c.tasks]}) for c in service.results.values()]}

    @app.post('/api/refresh')
    async def refresh(request: Request):
        await service.refresh()
        if service.annotation_error:
            raise HTTPException(503, '注釈DBの更新に失敗しました。保存領域を確認してください')
        return {'status': 'ok'}

    @app.get('/api/schedules/{task_id}/command')
    def command(task_id: str):
        # Use the collected snapshot, never a request-supplied filesystem path.
        for collection in service.results.values():
            for task in collection.tasks:
                if task.id == task_id:
                    if task._raw_command is None:
                        raise HTTPException(404, 'コマンドを分離できない設定です')
                    return {'id': task.id, 'command': task._raw_command,
                            'stale': collection.stale}
        raise HTTPException(404, 'タスクが見つかりません。再取得してください')

    @app.get('/api/timeline')
    def timeline(start: date, q: str = '', category: str = '', provider: str = '', enabled: str = '', frequency: Frequency = 'all', tag: list[int] = Query(default=[], max_length=200), tag_match: Literal['any', 'all'] = 'any'):
        if not 1970 <= start.year <= 2199:
            raise HTTPException(422, '表示日は1970年から2199年の範囲で指定してください')
        begin = datetime.combine(start, time(), ZoneInfo(zone))
        end = begin + timedelta(days=7)
        events = []
        cache = {}
        limited = False
        for task in tasks(q, category, provider, enabled, frequency, tag, tag_match):
            if task.enabled is not True or task.collection_status != 'ok':
                continue
            expression = task.schedule.expression
            if expression not in cache:
                cache[expression] = occurrences(expression, begin, end, zone)
            for at in cache[expression]:
                if len(events) >= 20000:
                    limited = True
                    break
                events.append({'task_id': task.id, 'at': at, 'category': task.category, 'name': task.name})
            if limited:
                break
        return {'start': begin, 'end': end, 'events': events, 'truncated': limited, 'timezone': zone}

    @app.get('/api/month')
    def month(month: date, q: str = '', category: str = '', provider: str = '', enabled: str = '', frequency: Frequency = 'all', tag: list[int] = Query(default=[], max_length=200), tag_match: Literal['any', 'all'] = 'any'):
        if not 1970 <= month.year <= 2199:
            raise HTTPException(422, '表示月は1970年から2199年の範囲で指定してください')
        begin = datetime.combine(month.replace(day=1), time(), ZoneInfo(zone))
        end = (begin.replace(day=28) + timedelta(days=4)).replace(day=1)
        days = []
        for task in tasks(q, category, provider, enabled, frequency, tag, tag_match):
            if task.enabled is not True or task.collection_status != 'ok':
                continue
            for summary in month_summary(task.schedule.expression, begin, end):
                days.append({**summary, 'task_id': task.id, 'name': task.name, 'category': task.category})
        return {'start': begin, 'end': end, 'days': days, 'timezone': zone}

    @app.get('/api/export.csv')
    def export(q: str = '', category: str = '', provider: str = '', enabled: str = '', frequency: Frequency = 'all', tag: list[int] = Query(default=[], max_length=200), tag_match: Literal['any', 'all'] = 'any'):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['名前', 'カテゴリ', '提供元', '有効状態', 'cron式', 'タイムゾーン', '次回実行予定', '設定場所', '取得元', '取得状態', 'コマンド（非表示）', 'タグ', '元の名前'])
        for task in tasks(q, category, provider, enabled, frequency, tag, tag_match):
            row = [task.name, task.category, task.provider, str(task.enabled), task.schedule.expression,
                   zone, task.next_runs[0].isoformat() if task.next_runs else '', task.configuration_location,
                   task.source.location, task.collection_status, task.command, ' / '.join(t.name for t in task.tags), task.original_name]
            writer.writerow(["'" + cell if cell.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else cell for cell in row])
        return Response('\ufeff' + output.getvalue(), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="qsv-schedules.csv"'})

    @app.get('/')
    def index():
        return FileResponse(WEB / 'index.html')

    app.mount('/static', StaticFiles(directory=WEB), name='static')
    return app


app = create_app()
