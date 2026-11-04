from datetime import datetime
from zoneinfo import ZoneInfo
from src.collectors.cron import CronCollector
from src.services.schedules import next_runs, occurrences

NOW = datetime(2026, 10, 25, 12, tzinfo=ZoneInfo('Asia/Tokyo'))


def collect(tmp_path, text):
    path = tmp_path / 'crontab'
    path.write_text(text)
    return CronCollector(path, 'Asia/Tokyo').collect(NOW)


def test_parse_stable_ids_and_secrets(tmp_path):
    line = '0 3 * * 0 /sbin/hwclock --password=SECRET; curl https://user:secret@example.org'
    result = collect(tmp_path, '# comment\nSHELL=/bin/sh\n' + line + '\n' + line)
    assert result.status == 'ok'
    assert all(t.collected_at == NOW for t in result.tasks)
    assert len(result.tasks) == 2
    assert result.tasks[0].id != result.tasks[1].id
    assert result.tasks[0].id == collect(tmp_path, '\n\n' + line).tasks[0].id
    assert 'SECRET' not in result.model_dump_json()
    assert 'user:secret' not in result.model_dump_json()
    assert 'hwclock' in result.tasks[0].command
    assert result.tasks[0].schedule.description == '毎週日曜日 03:00'


def test_unsupported_and_empty(tmp_path):
    assert collect(tmp_path, '# only comment').status == 'empty'
    result = collect(tmp_path, '@reboot /example/task\n70 3 * * * /example/task\n0 3 * * * /example/task')
    assert result.status == 'partial'
    assert len(result.tasks) == 3
    assert all(t.collected_at == NOW for t in result.tasks)
    assert [t.collection_status for t in result.tasks] == ['parse_error', 'parse_error', 'ok']
    assert CronCollector(tmp_path / 'absent', 'Asia/Tokyo').collect(NOW).status == 'unavailable'


def test_timezone_directive_not_guessed(tmp_path):
    result = collect(tmp_path, 'CRON_TZ=UTC\n0 3 * * * /example/task')
    assert result.status == 'partial'
    assert result.tasks[0].next_runs == []


def test_next_runs_and_dom_dow_or():
    assert next_runs('0 3 * * 0', NOW)[0].isoformat() == '2026-11-01T03:00:00+09:00'
    runs = next_runs('0 3 1 * 0', NOW)
    assert runs[0].day == 1
    assert runs[1].day == 8  # Sunday OR first day of month
    assert next_runs('0 0 31 2 *', NOW) == []


def test_dst_gap_and_fold():
    tz = ZoneInfo('America/New_York')
    gap = occurrences('30 2 * * *', datetime(2026, 3, 8, tzinfo=tz), datetime(2026, 3, 9, tzinfo=tz), str(tz))
    assert gap == []
    fold = occurrences('30 1 * * *', datetime(2026, 11, 1, tzinfo=tz), datetime(2026, 11, 2, tzinfo=tz), str(tz))
    assert len(fold) == 2
    assert fold[0].timestamp() != fold[1].timestamp()


def test_resource_limits(tmp_path):
    result = collect(tmp_path, '* * * * * /example/task\n' * 501)
    assert result.status == 'partial'
    assert len(result.tasks) == 500
    assert collect(tmp_path, 'x' * (1024 * 1024 + 1)).status == 'parse_error'


def test_malformed_rows_do_not_disclose_commands(tmp_path):
    result = collect(tmp_path, '@reboot curl https://user:SECRET@example.org --token=SECRET hello world\nSECRET value more words here /sbin/task')
    assert 'SECRET' not in result.model_dump_json()
    assert result.status == 'partial'


def test_dst_next_runs_consistent():
    tz = ZoneInfo('America/New_York')
    spring = next_runs('30 2 * * *', datetime(2026, 3, 8, tzinfo=tz))
    assert spring[0].isoformat() == '2026-03-09T02:30:00-04:00'
    fall = next_runs('30 1 * * *', datetime(2026, 11, 1, tzinfo=tz))
    assert fall[0].timestamp() < fall[1].timestamp()
    assert fall[0].hour == fall[1].hour == 1
