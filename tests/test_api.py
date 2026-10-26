from fastapi.testclient import TestClient
from src.api import create_app


def test_api_export_and_refresh(tmp_path):
    path = tmp_path / 'cron'
    path.write_text('0 3 * * * /example/task --token=SECRET\n@reboot SECRET')
    app = create_app(path, 'Asia/Tokyo', allowed_proxy_ips='192.168.10.10')
    with TestClient(app, client=('192.168.10.10', 12345)) as client:
        response = client.get('/api/schedules')
        assert response.status_code == 200
        assert 'SECRET' not in response.text
        data = response.json()
        assert len(data['tasks']) == 2
        assert data['collections'][1]['status'] == 'unsupported'
        assert client.get('/api/schedules?category=backup').json()['tasks'] == []
        assert client.get('/api/schedules?enabled=false').json()['tasks'] == []
        timeline = client.get('/api/timeline?start=2026-10-26').json()
        assert len(timeline['events']) == 7
        assert timeline['events'][0]['at'] == '2026-10-26T03:00:00+09:00'
        csv = client.get('/api/export.csv')
        assert 'SECRET' not in csv.text
        assert "'@unsupported" in csv.text
        assert client.post('/api/refresh', headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.post('/api/refresh', headers={'Origin': 'https://testserver'}).status_code == 200
        path.unlink()
        assert client.post('/api/refresh').status_code == 200
        stale = client.get('/api/schedules').json()
        assert stale['collections'][0]['stale']
        assert len(stale['tasks']) == 2
        assert stale['collections'][0]['previous_status'] == 'partial'
        assert client.get('/').status_code == 200
        assert "frame-ancestors 'none'" in client.get('/').headers['content-security-policy']
        assert client.get('/api/timeline?start=invalid').status_code == 422
