from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from src.api import create_app
from src.services.schedules import month_summary, occurrences, runs_per_active_day


@pytest.mark.parametrize('expression,count', [
    ('* * * * *', 1440), ('*/5 * * * *', 288), ('0 * * * *', 24),
    ('0 */2 * * *', 12), ('0,30 3 * * *', 2), ('0 3 1 * *', 1),
    ('*/5 * 1 * *', 288), ('0-59/15 0-23/6 * * SUN', 16),
])
def test_nominal_frequency(expression, count):
    assert runs_per_active_day(expression) == count


def test_month_aggregation_dense_jobs_and_real_month_dates():
    zone = ZoneInfo('Asia/Tokyo')
    start = datetime(2026, 11, 1, tzinfo=zone)
    end = datetime(2026, 12, 1, tzinfo=zone)
    dense = month_summary('* * * * *', start, end)
    assert len(dense) == 30
    assert sum(row['count'] for row in dense) == 43200
    assert all(row['count'] == 1440 for row in dense)
    monthly = month_summary('0 3 1 * *', start, end)
    assert [(row['day'], row['count']) for row in monthly] == [('2026-11-01', 1)]
    assert monthly[0]['first_run'].isoformat() == '2026-11-01T03:00:00+09:00'
    feb = datetime(2028, 2, 1, tzinfo=zone)
    march = datetime(2028, 3, 1, tzinfo=zone)
    assert month_summary('0 3 31 * *', feb, march) == []
    assert [row['day'] for row in month_summary('0 3 29 2 *', feb, march)] == ['2028-02-29']


@pytest.mark.parametrize('expression', ['* * * * *', '30 1 * * *', '30 2 * * *', '0 3 1 * 0'])
@pytest.mark.parametrize('year,month', [(2026, 3), (2026, 11)])
def test_month_aggregation_matches_exact_daily_occurrences(expression, year, month):
    zone = ZoneInfo('America/New_York')
    start = datetime(year, month, 1, tzinfo=zone)
    end = datetime(year, month+1, 1, tzinfo=zone)
    summaries = {row['day']: row for row in month_summary(expression, start, end)}
    # Compare on transition day as well as the first day (DOM/DOW OR).
    from datetime import timedelta
    for day_number in (1, 8):
        day = start.replace(day=day_number)
        runs = occurrences(expression, day, day+timedelta(days=1), str(zone))
        summary = summaries.get(day.date().isoformat())
        assert (summary['count'] if summary else 0) == len(runs)
        if runs:
            assert summary['first_run'].timestamp() == runs[0].timestamp()


def test_frequency_filter_applies_before_timeline_limit_and_to_exports(tmp_path):
    path = tmp_path / 'cron'
    path.write_text('* * * * * /example/minutely-a\n* * * * * /example/minutely-b\n* * * * * /example/minutely-c\n0 * * * * /example/hourly\n0 3 1 * * /example/monthly\n0 4 * * * /example/daily\n@reboot /example/unknown')
    with TestClient(create_app(path, allowed_proxy_ips='127.0.0.1'), client=('127.0.0.1', 12345)) as client:
        all_data = client.get('/api/schedules').json()
        assert len(all_data['tasks']) == 7
        sparse = client.get('/api/schedules?frequency=nonfrequent').json()
        assert len(sparse['tasks']) == 3
        assert sparse['hidden_by_frequency'] == 4
        assert any(t['collection_status'] == 'parse_error' for t in sparse['tasks'])
        assert len(client.get('/api/schedules?frequency=frequent').json()['tasks']) == 4
        # Start on a month boundary so the monthly event must survive filtering.
        weekly = client.get('/api/timeline?start=2026-11-01&frequency=nonfrequent').json()
        assert not weekly['truncated']
        assert len(weekly['events']) == 8
        monthly_task = next(t for t in sparse['tasks'] if t['schedule']['expression'] == '0 3 1 * *')
        assert monthly_task['id'] in {e['task_id'] for e in weekly['events']}
        csv = client.get('/api/export.csv?frequency=nonfrequent').text
        assert '* * * * *' not in csv
        assert '0 3 1 * *' in csv
        monthly = client.get('/api/month?month=2026-11-15&frequency=nonfrequent').json()
        assert monthly['start'].startswith('2026-11-01')
        assert monthly['end'].startswith('2026-12-01')
        assert len(monthly['days']) == 31  # 30 daily rows + monthly row
        dense_month = client.get('/api/month?month=2026-11-01&frequency=frequent').json()
        assert len(dense_month['days']) == 120
        assert sum(r['count'] for r in dense_month['days']) == 3*43200 + 24*30
        assert client.get('/api/schedules?frequency=invalid').status_code == 422
        assert client.get('/api/month?month=2200-01-01').status_code == 422
        assert client.get('/api/month?month=bad-date').status_code == 422
