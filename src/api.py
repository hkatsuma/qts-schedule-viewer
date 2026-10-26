import asyncio
import csv
import io
import os
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from src.collectors.cron import CronCollector
from src.services.collection import CollectionService
from src.services.schedules import occurrences, next_runs

WEB = Path(__file__).parent / 'web'


def create_app(path: Path | None = None, timezone: str | None = None) -> FastAPI:
    zone = timezone or os.getenv('QSV_TIMEZONE', 'Asia/Tokyo')
    ZoneInfo(zone)  # Fail clearly at startup on a misconfigured timezone.
    service = CollectionService(CronCollector(path or Path(os.getenv('QSV_CRONTAB_PATH', '/host/crontab')), zone),
                                max(30, int(os.getenv('QSV_REFRESH_SECONDS', '300'))))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await service.refresh()
        background = asyncio.create_task(service.run())
        yield
        background.cancel()
        with suppress(asyncio.CancelledError):
            await background

    app = FastAPI(title='QTS Schedule Viewer', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.collection = service

    @app.middleware('http')
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def tasks(q: str = '', category: str = '', provider: str = '', enabled: str = ''):
        result = []
        for collection in service.results.values():
            for stored in collection.tasks:
                task = stored.model_copy(deep=True)
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
    def schedules(q: str = Query('', max_length=200), category: str = '', provider: str = '', enabled: str = ''):
        return {'timezone': zone, 'tasks': tasks(q, category, provider, enabled),
                'collections': list(service.results.values())}

    @app.post('/api/refresh')
    async def refresh(request: Request):
        # Reject cross-origin browser requests; this only refreshes the cache.
        origin = request.headers.get('origin')
        if origin and (urlsplit(origin).scheme not in ('http', 'https') or urlsplit(origin).netloc != request.url.netloc):
            raise HTTPException(403, '異なるサイトからの再取得はできません')
        await service.refresh()
        return {'status': 'ok'}

    @app.get('/api/timeline')
    def timeline(start: date, q: str = '', category: str = '', provider: str = '', enabled: str = ''):
        if not 1970 <= start.year <= 2199:
            raise HTTPException(422, '表示日は1970年から2199年の範囲で指定してください')
        begin = datetime.combine(start, time(), ZoneInfo(zone))
        end = begin + timedelta(days=7)
        events = []
        cache = {}
        limited = False
        for task in tasks(q, category, provider, enabled):
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

    @app.get('/api/export.csv')
    def export(q: str = '', category: str = '', provider: str = '', enabled: str = ''):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['名前', 'カテゴリ', '提供元', '有効状態', 'cron式', 'タイムゾーン', '次回実行予定', '設定場所', '取得元', '取得状態', 'コマンド（機密保護）'])
        for task in tasks(q, category, provider, enabled):
            row = [task.name, task.category, task.provider, str(task.enabled), task.schedule.expression,
                   zone, task.next_runs[0].isoformat() if task.next_runs else '', task.configuration_location,
                   task.source.location, task.collection_status, task.command]
            writer.writerow(["'" + cell if cell.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else cell for cell in row])
        return Response('\ufeff' + output.getvalue(), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="qsv-schedules.csv"'})

    @app.get('/')
    def index():
        return FileResponse(WEB / 'index.html')

    app.mount('/static', StaticFiles(directory=WEB), name='static')
    return app


app = create_app()
