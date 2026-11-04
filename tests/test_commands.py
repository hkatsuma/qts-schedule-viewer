from fastapi.testclient import TestClient
from src.api import create_app


PEER = '192.168.0.2'
RAW = '/example/task  --token=PRIVATE_MARKER; echo "<img src=x onerror=alert(1)>" # note'


def test_commands_only_disclosed_on_demand(tmp_path):
    path = tmp_path / 'cron'
    path.write_text(f'0 3 * * * {RAW}\n0 3 * * * {RAW}\n99 3 * * * {RAW}\n@reboot PRIVATE_MARKER\nPRIVATE_MARKER invalid row\nTOKEN=PRIVATE_MARKER\n')
    app = create_app(path, allowed_proxy_ips=PEER)
    with TestClient(app, client=(PEER, 12345)) as client:
        listing = client.get('/api/schedules')
        tasks = listing.json()['tasks']
        assert len(tasks) == 5
        assert sum(t['command_available'] for t in tasks) == 3
        for route in ('/api/schedules', '/api/export.csv', '/api/timeline?start=2026-11-02', '/api/month?month=2026-11-01', '/openapi.json'):
            assert 'PRIVATE_MARKER' not in client.get(route).text
        assert client.get('/api/schedules?q=PRIVATE_MARKER').json()['tasks'] == []
        stored = app.state.collection.results['cron']
        assert 'PRIVATE_MARKER' not in stored.model_dump_json()
        assert 'PRIVATE_MARKER' not in repr(stored)
        assert 'PRIVATE_MARKER' not in stored.model_copy(deep=True).model_dump_json()
        assert tasks[0]['id'] != tasks[1]['id']
        for task in tasks:
            response = client.get(f"/api/schedules/{task['id']}/command")
            assert response.headers['Cache-Control'] == 'no-store'
            if task['command_available']:
                assert response.json() == {'id': task['id'], 'command': RAW, 'stale': False}
            else:
                assert response.status_code == 404
                assert 'PRIVATE_MARKER' not in response.text
        assert client.get('/api/schedules/unknown/command').status_code == 404


def test_command_snapshot_refresh_and_stale_cache(tmp_path):
    path = tmp_path / 'cron'
    path.write_text(f'0 3 * * * {RAW}')
    app = create_app(path, allowed_proxy_ips=PEER)
    with TestClient(app, client=(PEER, 12345)) as client:
        task = client.get('/api/schedules').json()['tasks'][0]
        route = f"/api/schedules/{task['id']}/command"
        path.write_text('0 3 * * * /example/changed')
        # Reading a command must use the same cached definition as the schedule.
        assert client.get(route).json()['command'] == RAW
        path.unlink()
        assert client.post('/api/refresh').status_code == 200
        stale_task = client.get('/api/schedules').json()['tasks'][0]
        assert stale_task['collected_at'] == task['collected_at']
        assert task['collected_at'] is not None
        assert client.get(route).json()['stale'] is True
        assert client.get(route).json()['command'] == RAW
        path.write_text('0 3 * * * /example/changed')
        assert client.post('/api/refresh').status_code == 200
        assert client.get(route).status_code == 404
        changed = client.get('/api/schedules').json()['tasks'][0]
        assert changed['collected_at'] != task['collected_at']
        assert client.get(f"/api/schedules/{changed['id']}/command").json()['command'] == '/example/changed'
    with TestClient(app, client=('192.168.0.3', 12345)) as client:
        response = client.get(route, headers={'X-Forwarded-For': PEER})
        assert response.status_code == 403
        assert 'PRIVATE_MARKER' not in response.text
