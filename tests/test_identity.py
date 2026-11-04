from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from src.api import create_app
from src.collectors.cron import CronCollector
from src.services.identity import cron_context_id, cron_definition_id

NOW = datetime(2026, 11, 4, 12, tzinfo=ZoneInfo('Asia/Tokyo'))
ROW = '0 3 * * * /example/job  --mode="daily report" # job-a'


def collect(tmp_path, text, timezone='Asia/Tokyo', filename='cron'):
    path = tmp_path / filename
    path.write_text(text)
    return CronCollector(path, timezone).collect(NOW)


@pytest.mark.parametrize('text', [
    ROW, '\n\n' + ROW + '\n', '# unrelated comment\n' + ROW,
    '\t  ' + ROW, ROW.replace('0 3 * * * ', '0\t3   *\t*  *\t '),
])
def test_formatting_keeps_definition_and_row_id(tmp_path, text):
    before = collect(tmp_path, ROW).tasks[0]
    after = collect(tmp_path, text).tasks[0]
    assert before.definition_id == after.definition_id
    assert before.id == after.id
    assert len(before.definition_id) == len('cron-v1-') + 64


@pytest.mark.parametrize('changed', [
    ROW.replace('0 3 ', '0 4 ', 1),
    ROW.replace('0 3 ', '00 03 ', 1),
    ROW.replace('/example/job', '/example/other'),
    ROW.replace('  --mode', ' --mode'),
    ROW.replace('daily report', 'daily  report'),
    ROW.replace('"daily report"', "'daily report'"),
    ROW.replace('# job-a', '# job-b'),
    ROW.replace(' # job-a', ''),
    ROW + ' ',
    ROW + '; /example/next',
    ROW + ' > /example/output',
    ROW + ' && /example/next',
    ROW + ' | /example/next',
])
def test_semantic_or_uncertain_changes_are_new_definitions(tmp_path, changed):
    before = collect(tmp_path, ROW).tasks[0]
    after = collect(tmp_path, changed).tasks[0]
    assert before.definition_id != after.definition_id
    assert before.id != after.id


def test_job_order_and_mount_location_do_not_define_identity(tmp_path):
    other = '0 5 * * * /example/other'
    before = collect(tmp_path, ROW + '\n' + other)
    after = collect(tmp_path, other + '\n' + ROW, filename='different-mount')
    assert [t.id for t in before.tasks] == [t.id for t in reversed(after.tasks)]
    assert before.tasks[0].name != after.tasks[1].name


def test_duplicates_share_definition_but_remain_separate_schedules(tmp_path):
    other = '0 5 * * * /example/other'
    before = collect(tmp_path, ROW + '\n' + ROW + '\n' + other)
    after = collect(tmp_path, other + '\n' + ROW + '\n' + ROW)
    duplicates = before.tasks[:2]
    assert len({t.definition_id for t in duplicates}) == 1
    assert len({t.id for t in duplicates}) == 2
    assert [t.duplicate_count for t in before.tasks] == [2, 2, 1]
    assert {t.id for t in before.tasks} == {t.id for t in after.tasks}
    remaining = collect(tmp_path, ROW).tasks[0]
    assert remaining.definition_id == duplicates[0].definition_id
    assert remaining.duplicate_count == 1
    # Ordinal ids identify the current snapshot, not historical physical lines.
    added = collect(tmp_path, ROW + '\n' + ROW + '\n' + ROW).tasks
    assert {t.definition_id for t in added} == {remaining.definition_id}
    assert [t.duplicate_count for t in added] == [3, 3, 3]


def test_distinct_schedules_or_comments_are_not_duplicates(tmp_path):
    tasks = collect(tmp_path, '\n'.join([ROW, ROW.replace('0 3 ', '0 4 ', 1),
                                          ROW.replace('# job-a', '# job-b')])).tasks
    assert len({t.definition_id for t in tasks}) == 3
    assert [t.duplicate_count for t in tasks] == [1, 1, 1]


def test_disappearing_and_returning_definition_is_deterministic(tmp_path):
    before = collect(tmp_path, ROW).tasks[0]
    assert collect(tmp_path, '# removed').tasks == []
    assert collect(tmp_path, ROW).tasks[0].definition_id == before.definition_id
    replacement = collect(tmp_path, ROW.replace('/example/job', '/example/new')).tasks[0]
    assert replacement.definition_id != before.definition_id


@pytest.mark.parametrize('declaration', [
    'SHELL=/bin/sh', 'PATH=/example/bin', 'MODE=PRIVATE_MARKER',
    'CRON_TZ=UTC', 'TZ=Asia/Tokyo',
])
def test_environment_changes_invalidate_definitions_without_disclosure(tmp_path, declaration):
    before = collect(tmp_path, ROW).tasks[0]
    changed = collect(tmp_path, declaration + '\n' + ROW)
    assert changed.tasks[0].definition_id != before.definition_id
    assert 'PRIVATE_MARKER' not in changed.model_dump_json()
    assert 'PRIVATE_MARKER' not in repr(changed)


def test_environment_boundaries_and_order_are_preserved(tmp_path):
    tasks = collect(tmp_path, ROW + '\nMODE=one\n' + ROW).tasks
    assert tasks[0].definition_id != tasks[1].definition_id
    before = collect(tmp_path, 'PATH=/example/bin\nMODE=one\n' + ROW).tasks[0]
    reordered = collect(tmp_path, 'MODE=one\nPATH=/example/bin\n' + ROW).tasks[0]
    assert before.definition_id != reordered.definition_id
    # Even declarations after a job matter conservatively: QTS scoping is not
    # inferred and no annotation silently crosses an environment change.
    assert tasks[0].definition_id != collect(tmp_path, ROW).tasks[0].definition_id


def test_timezone_and_logical_source_are_part_of_identity(tmp_path):
    task = collect(tmp_path, ROW).tasks[0]
    assert task.definition_id != collect(tmp_path, ROW, timezone='UTC').tasks[0].definition_id
    options = dict(scope=0, expression='0 3 * * *', command='/example/job', raw_line='ignored')
    a = cron_context_id(source='source-a', timezone='Asia/Tokyo', environment=())
    b = cron_context_id(source='source-b', timezone='Asia/Tokyo', environment=())
    assert cron_definition_id(context_id=a, **options) != cron_definition_id(context_id=b, **options)


def test_opaque_and_invalid_rows_are_conservative(tmp_path):
    text = '@reboot /example/job PRIVATE_MARKER'
    before = collect(tmp_path, text).tasks[0]
    assert not before.command_available
    changed = collect(tmp_path, text.replace('PRIVATE_MARKER', 'different')).tasks[0]
    assert before.definition_id != changed.definition_id
    assert collect(tmp_path, ' ' + text).tasks[0].definition_id != before.definition_id
    invalid = collect(tmp_path, '99 3 * * * /example/job').tasks[0]
    assert invalid.collection_status == 'parse_error'
    assert invalid.definition_id != collect(tmp_path, '0 3 * * * /example/job').tasks[0].definition_id


def test_trailing_command_whitespace_is_not_discarded(tmp_path):
    row = '0 3 * * * /example/job escaped\\ '
    task = collect(tmp_path, row).tasks[0]
    assert task._raw_command == '/example/job escaped\\ '
    assert task.definition_id != collect(tmp_path, row.rstrip()).tasks[0].definition_id


def test_non_ascii_field_separator_is_not_normalized(tmp_path):
    standard = collect(tmp_path, ROW).tasks[0]
    opaque = collect(tmp_path, ROW.replace('0 3 ', '0\u30003 ', 1)).tasks[0]
    assert opaque.definition_id != standard.definition_id
    assert not opaque.command_available


def test_empty_command_is_not_a_standard_definition(tmp_path):
    task = collect(tmp_path, '0 3 * * *   ').tasks[0]
    assert task.collection_status == 'parse_error'
    assert not task.command_available


def test_v1_persisted_key_contract(tmp_path):
    # Persisted annotations must not silently change keys after a refactor.
    task = collect(tmp_path, '0 3 * * * /example/job').tasks[0]
    assert task.definition_id == 'cron-v1-e26941c18e41d783f6404fb72b99e4a8c56d2d8e50f637975ed308e773fdd2b5'
    assert task.id == task.definition_id + '-1'


def test_duplicate_count_is_limited_to_collected_rows(tmp_path):
    result = collect(tmp_path, (ROW + '\n') * 501)
    assert result.status == 'partial'
    assert len(result.tasks) == 500
    assert {task.duplicate_count for task in result.tasks} == {500}


def test_api_identity_survives_formatting_but_not_replacement(tmp_path):
    path = tmp_path / 'cron'
    path.write_text(ROW + '\n' + ROW)
    app = create_app(path, allowed_proxy_ips='192.168.0.2')
    with TestClient(app, client=('192.168.0.2', 12345)) as client:
        tasks = client.get('/api/schedules').json()['tasks']
        assert len(tasks) == 2
        assert tasks[0]['definition_id'] == tasks[1]['definition_id']
        assert [t['duplicate_count'] for t in tasks] == [2, 2]
        route = f"/api/schedules/{tasks[0]['id']}/command"
        path.write_text('# comment\n' + ROW.replace('0 3 * * * ', '0\t3 *  * *\t') + '\n' + ROW)
        assert client.post('/api/refresh').status_code == 200
        assert client.get(route).status_code == 200
        updated = client.get('/api/schedules').json()['tasks']
        assert {t['id'] for t in tasks} == {t['id'] for t in updated}
        events = client.get('/api/timeline?start=2026-11-02').json()['events']
        assert len(events) == 14
        assert {event['task_id'] for event in events} == {t['id'] for t in tasks}
        path.write_text(ROW.replace('0 3 ', '0 4 ', 1))
        assert client.post('/api/refresh').status_code == 200
        assert client.get(route).status_code == 404
        assert client.get('/api/schedules').json()['tasks'][0]['definition_id'] != tasks[0]['definition_id']
