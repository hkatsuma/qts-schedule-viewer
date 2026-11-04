"""Run with Playwright + Chromium installed: python tests/browser/command_visibility.py."""
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import uvicorn
from playwright.sync_api import sync_playwright, expect
from src.api import create_app

RAW = '/example/task --token=PRIVATE_MARKER; echo "<img src=x onerror=alert(1)>"'


def check(page, base):
    requests, errors = [], []
    page.on('request', lambda request: requests.append(request.url) if request.url.endswith('/command') else None)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base)
    page.locator('[data-view=list]').click()
    page.locator('#rows button').first.click()
    button = page.locator('.command-toggle').first
    body = page.locator('#command-0')
    expect(button).to_have_attribute('aria-label','コマンドを表示')
    expect(body).to_have_text('非表示')
    assert not requests
    detail = page.locator('#detail-body')
    expect(detail).not_to_contain_text('タイムゾーン:')
    expect(detail).not_to_contain_text('管理画面の有無')
    expect(detail).not_to_contain_text('機密情報保護')
    expect(page.locator('#notice')).to_contain_text('Asia/Tokyo')
    expect(page.locator('.task-collection')).to_contain_text('正常 · 取得 ')
    expect(page.locator('#rows td').nth(5)).to_contain_text('正常 · 取得 ')
    assert button.locator('svg').count() == 1
    button.click()
    expect(body).to_have_text(RAW)
    assert len(requests) == 1
    expect(detail).not_to_contain_text('収集時点のコマンドです')
    expect(detail).not_to_contain_text('実行・編集はできません')
    assert page.locator('#detail img').count() == 0
    button.click()
    expect(body).to_have_text('非表示')
    expect(body).to_have_text('非表示')
    button.click()
    expect(body).to_have_text(RAW)
    page.keyboard.press('Escape')
    expect(body).to_have_text('非表示')
    page.locator('#rows button').first.click()
    expect(button).to_have_attribute('aria-label','コマンドを表示')
    assert len(requests) == 2
    button.click()
    expect(body).to_have_text(RAW)
    page.locator('#close').click()
    expect(body).to_have_text('非表示')

    # A late response must not repopulate a closed or refreshed dialog.
    held = []
    page.route('**/command', lambda route: held.append(route))
    page.locator('#rows button').first.click()
    button.click()
    expect(button).to_have_attribute('aria-expanded', 'true')
    page.wait_for_timeout(100)
    assert held
    page.locator('#close').click()
    held.pop().fulfill(json={'id': 'unused', 'command': RAW, 'stale': False})
    expect(body).to_have_text('非表示')
    page.locator('#rows button').first.click()
    button.click()
    page.wait_for_timeout(100)
    page.evaluate('load()')
    held.pop().fulfill(json={'id': 'unused', 'command': RAW, 'stale': False})
    expect(body).to_have_text('非表示')
    expect(button).to_have_attribute('aria-expanded', 'false')
    page.unroute('**/command')

    # Independent controls for several tasks grouped in one timeline marker.
    page.evaluate('showTasks(data.tasks)')
    buttons = page.locator('.command-toggle')
    assert buttons.count() == 2
    assert page.locator('.task-detail').count() == 2
    for card in page.locator('.task-detail').all():
        assert card.locator('.command-toggle').count() == 1
        assert card.locator('.task-collection').count() == 1
    buttons.nth(1).click()
    expect(page.locator('#command-1')).to_have_text(RAW)
    expect(page.locator('#command-0')).to_have_text('非表示')
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.locator('#detail').evaluate('(node) => node.scrollWidth <= node.clientWidth')
    page.locator('#close').click()
    assert not errors, errors
    assert 'PRIVATE_MARKER' not in page.content()


def main():
    with TemporaryDirectory(prefix='qsv-browser-') as temp:
        path = Path(temp) / 'cron'
        path.write_text(f'0 3 * * * {RAW}\n0 3 * * * {RAW}\n')
        app = create_app(path, allowed_proxy_ips='127.0.0.1', db_path=Path(temp) / 'qsv.sqlite3')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
            thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(.05)
                assert server.started
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page()
                    check(page, f'http://127.0.0.1:{port}')
                    browser.close()
            finally:
                server.should_exit = True
                thread.join(timeout=10)
    print('Command visibility browser checks passed')


if __name__ == '__main__':
    main()
