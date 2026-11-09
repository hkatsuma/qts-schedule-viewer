"""Run with Playwright + Chromium: python tests/browser/annotations.py."""
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

ROWS = '0 3 * * * /example/job --token=PRIVATE_MARKER\n0 3 * * * /example/job --token=PRIVATE_MARKER\n0 4 * * * /example/other\n'


def check(page, base, path):
    errors=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('dialog', lambda dialog: dialog.accept())
    page.goto(base)
    page.locator('[data-view=annotations]').click()
    page.locator('#new-tag').fill('保守')
    page.locator('#tag-create-button').click()
    expect(page.locator('#tag-management input')).to_have_value('保守')
    page.locator('#new-tag').fill('夜間')
    page.locator('#tag-create-button').click()
    expect(page.locator('#tag-management input')).to_have_count(2)
    page.locator('[data-view=list]').click()
    page.locator('#rows button').first.click()
    page.locator('#detail .annotation-edit').click()
    expect(page.locator('#annotation-scope')).to_contain_text('2 行')
    page.locator('#display-name').fill('毎日の保守')
    page.locator('#annotation-tags label').filter(has_text='保守').locator('input').check()
    page.locator('#annotation-save').click()
    expect(page.locator('#annotation-editor')).not_to_be_visible()
    expect(page.locator('#rows button').filter(has_text='毎日の保守')).to_have_count(2)
    page.locator('#tag-options label').filter(has_text='保守').locator('input').check()
    expect(page.locator('#rows tr')).to_have_count(2)
    assert 'tag=' in page.locator('#export').get_attribute('href')
    page.locator('[data-view=month]').click()
    expect(page.locator('.month-task').first).to_contain_text('毎日の保守')
    page.locator('[data-view=week]').click()
    expect(page.locator('.event').first).to_contain_text('2件')
    page.locator('#clear-tags').click()
    page.locator('[data-view=list]').click()
    expect(page.locator('#rows tr')).to_have_count(3)
    # A concurrent update must retain the draft and present a reload action.
    page.locator('#rows button').first.click()
    page.locator('#detail .annotation-edit').click()
    page.locator('#display-name').fill('古い編集')
    page.evaluate('''async() => {
      const task=data.tasks[0];
      await writeAnnotation('/api/annotations/'+task.definition_id,'PUT',{
        version:task.annotation_version,display_name:'他の編集',tag_ids:task.tags.map(t=>t.id)});
    }''')
    page.locator('#annotation-save').click()
    expect(page.locator('#annotation-message')).to_contain_text('更新されました')
    expect(page.locator('#display-name')).to_have_value('古い編集')
    page.locator('#annotation-reload').click()
    expect(page.locator('#display-name')).to_have_value('他の編集')
    page.locator('#annotation-cancel').click()
    page.locator('#close').click()
    # A definition change cannot inherit annotations until explicitly copied.
    path.write_text(ROWS.replace('/example/job', '/example/replaced'))
    page.locator('#refresh').click()
    page.locator('[data-view=annotations]').click()
    source=page.locator('.annotation-record').filter(has=page.get_by_role('heading', name='他の編集', exact=True))
    expect(source).to_contain_text('現在は見つからないジョブ')
    source.locator('select').select_option(index=1)
    source.get_by_role('button', name='表示名とタグをコピー', exact=True).click()
    expect(page.locator('.annotation-record')).to_have_count(2)
    # Rename and delete tags globally, including archived annotations.
    tag_form=page.locator('.tag-management-row').filter(has=page.get_by_role('textbox', name='タグ名: 保守', exact=True))
    tag_form.locator('input').fill('メンテナンス')
    tag_form.get_by_role('button', name='名前を変更', exact=True).click()
    expect(page.get_by_role('textbox', name='タグ名: メンテナンス', exact=True)).to_be_visible()
    tag_form=page.locator('.tag-management-row').filter(has=page.get_by_role('textbox', name='タグ名: メンテナンス', exact=True))
    tag_form.get_by_role('button', name='削除', exact=True).click()
    expect(page.locator('#tag-management input')).to_have_count(1)
    # User-provided names and tags are text, including HTML-like content.
    page.locator('[data-view=list]').click()
    page.locator('#rows button').first.click()
    page.locator('#detail .annotation-edit').click()
    page.locator('#display-name').fill('<img src=x onerror=alert(1)>')
    page.locator('#annotation-save').click()
    expect(page.locator('#rows button').first).to_have_text('<img src=x onerror=alert(1)>')
    assert page.locator('img').count()==0
    page.locator('#rows button').first.click()
    page.locator('#detail .annotation-edit').click()
    page.screenshot(path='/tmp/qsv-annotations-editor.png')
    page.set_viewport_size({'width':390,'height':844})
    assert page.locator('#annotation-editor').evaluate('(n)=>n.scrollWidth<=n.clientWidth')
    page.locator('#annotation-cancel').click()
    page.locator('#close').click()
    page.reload()
    page.locator('[data-view=list]').click()
    expect(page.locator('#rows button').first).to_have_text('<img src=x onerror=alert(1)>')
    assert 'PRIVATE_MARKER' not in page.content()
    assert not errors, errors


def main():
    with TemporaryDirectory(prefix='qsv-annotations-browser-') as temp:
        path=Path(temp)/'cron'; path.write_text(ROWS)
        app=create_app(path,allowed_proxy_ips='127.0.0.1',db_path=Path(temp)/'qsv.sqlite3')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
            server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
            thread=Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True); thread.start()
            try:
                for _ in range(100):
                    if server.started: break
                    time.sleep(.05)
                assert server.started
                with sync_playwright() as playwright:
                    browser=playwright.chromium.launch()
                    check(browser.new_page(),f'http://127.0.0.1:{port}',path)
                    browser.close()
            finally:
                server.should_exit=True; thread.join(timeout=10)
    print('Annotation browser checks passed')


if __name__=='__main__': main()
