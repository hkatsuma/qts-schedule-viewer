import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from croniter import croniter
from functools import lru_cache


def validate(expression: str) -> None:
    # Deliberately exclude croniter extensions (seconds, hashes, random, L, #).
    if len(expression.split()) != 5 or not re.fullmatch(r'[0-9A-Za-z*,/\- ]+', expression):
        raise ValueError('標準5フィールド以外のcron式は未対応です')
    if re.search(r'\b(?:L|W|H|R)\b', expression, re.I) or not croniter.is_valid(expression):
        raise ValueError('不正または未対応のcron式です')


def describe(expression: str) -> str:
    minute, hour, day, month, weekday = expression.split()
    if minute.isdigit() and hour.isdigit() and day == month == '*':
        at = f'{int(hour):02}:{int(minute):02}'
        if weekday == '*':
            return f'毎日 {at}'
        if weekday.isdigit() and 0 <= int(weekday) <= 7:
            return f'毎週{"日月火水木金土日"[int(weekday)]}曜日 {at}'
    return f'cron（分 時 日 月 曜日）: {expression}'


def next_runs(expression: str, now: datetime, count: int = 3) -> list[datetime]:
    validate(expression)
    iterator = croniter(expression, now, max_years_between_matches=8)
    result = []
    try:
        for _ in range(count + 16):
            candidate = iterator.get_next(datetime)
            # croniter may shift a nonexistent 02:30 to 03:00. Such a
            # wall-clock time is not an occurrence of the original expression.
            roundtrip = candidate.astimezone(timezone.utc).astimezone(candidate.tzinfo)
            if roundtrip.replace(tzinfo=None) != candidate.replace(tzinfo=None):
                continue
            if not croniter.match(expression, candidate.replace(tzinfo=None)):
                continue
            result.append(candidate)
            if len(result) >= count:
                break
    except (ValueError, OverflowError):
        pass
    return result


@lru_cache(maxsize=32)
def occurrences(expression: str, start: datetime, end: datetime, zone: str) -> list[datetime]:
    # Iterate wall-clock candidates, then validate both folds by UTC roundtrip.
    # This omits nonexistent DST minutes and retains both repeated minutes.
    validate(expression)
    tz = ZoneInfo(zone)
    wall_start = start.astimezone(tz).replace(tzinfo=None)
    wall_end = end.astimezone(tz).replace(tzinfo=None)
    iterator = croniter(expression, wall_start - timedelta(microseconds=1), max_years_between_matches=8)
    result: dict[float, datetime] = {}
    try:
        for _ in range(11000):
            wall = iterator.get_next(datetime)
            if wall >= wall_end:
                break
            for fold in (0, 1):
                local = wall.replace(tzinfo=tz, fold=fold)
                utc = local.astimezone(timezone.utc)
                if utc.astimezone(tz).replace(tzinfo=None) != wall:
                    continue
                if start.timestamp() <= utc.timestamp() < end.timestamp():
                    result[utc.timestamp()] = local
    except (ValueError, OverflowError):
        pass
    return [result[key] for key in sorted(result)]
