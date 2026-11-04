import pytest
from fastapi.testclient import TestClient
from src.api import create_app
from src.services.access import IPAllowlist


@pytest.mark.parametrize('configured,peer,expected', [
    ('192.168.0.2', '192.168.0.2', True),
    ('192.168.0.2', '192.168.0.3', False),
    (' 192.168.0.2, fd7a:115c:a1e0::1 ', 'fd7a:115c:a1e0::1', True),
    ('192.168.0.2', '::ffff:192.168.0.2', True),
    ('::ffff:192.168.0.2', '192.168.0.2', True),
    ('', '192.168.0.2', False),
    ('192.168.0.2', None, False),
    ('192.168.0.2', 'testclient', False),
])
def test_peer_match(configured, peer, expected):
    assert IPAllowlist(configured).permits(peer) is expected


@pytest.mark.parametrize('value', ['*', '192.168.10.0/24', 'server-a', 'bad-ip', '127.0.0.1,', 'fe80::1%eth0'])
def test_invalid_configuration_fails_startup(value):
    with pytest.raises(ValueError, match='QSV_ALLOWED_PROXY_IPS'):
        create_app(allowed_proxy_ips=value)


@pytest.mark.parametrize('path', ['/', '/static/app.js', '/api/schedules', '/api/timeline?start=2026-10-26', '/api/export.csv', '/api/month?month=2026-11-01', '/openapi.json', '/api/schedules/unknown/command', '/healthz'])
def test_all_routes_reject_unlisted_peer_even_with_spoofed_headers(path):
    app = create_app(allowed_proxy_ips='192.168.0.2')
    with TestClient(app, client=('192.168.10.99', 12345)) as client:
        response = client.get(path, headers={
            'X-Forwarded-For': '192.168.0.2', 'X-Real-IP': '192.168.0.2',
            'Forwarded': 'for=192.168.0.2', 'X-Forwarded-Host': 'trusted.example',
        })
        assert response.status_code == 403
        assert response.text == 'Forbidden'
        assert response.headers['Cache-Control'] == 'no-store'
        assert client.post('/api/refresh').status_code == 403


def test_listed_proxy_can_forward_any_tailnet_client(tmp_path):
    path = tmp_path / 'cron'
    path.write_text('0 3 * * * /example/task')
    app = create_app(path, allowed_proxy_ips='192.168.0.2')
    with TestClient(app, client=('192.168.0.2', 12345)) as client:
        response = client.get('/api/schedules', headers={'X-Forwarded-For': '100.100.100.100'})
        assert response.status_code == 200
        assert len(response.json()['tasks']) == 1


def test_empty_allowlist_denies_and_health_is_local_only():
    app = create_app(allowed_proxy_ips='')
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        assert client.get('/healthz').status_code == 200
        assert client.get('/api/schedules').status_code == 403
        assert client.get('/').status_code == 403
        assert client.post('/api/refresh').status_code == 403
    with TestClient(app, client=('192.168.0.2', 12345)) as client:
        assert client.get('/healthz').status_code == 403


def test_environment_configuration(monkeypatch):
    monkeypatch.setenv('QSV_ALLOWED_PROXY_IPS', '192.168.0.2')
    app = create_app()
    with TestClient(app, client=('192.168.0.2', 12345)) as client:
        assert client.get('/healthz').status_code == 200
