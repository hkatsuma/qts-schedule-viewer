import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from src.models import Collection, Schedule, Source, Task
from src.services.schedules import describe, next_runs, validate, runs_per_active_day
from src.services.identity import cron_context_id, cron_definition_id

MAX_BYTES = 1024 * 1024
MAX_TASKS = 500
SOURCE_LOCATION = '/etc/config/crontab'
ENVIRONMENT_ASSIGNMENT = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$')


def safe_command(command: str) -> str:
    # Values and arbitrary arguments may contain secrets with no recognizable
    # key. Default responses reveal only an allowlisted executable.
    first = command.split()[0] if command.split() else ''
    known = {'/sbin/vs_refresh': 'QTS ストレージ更新',
             '/sbin/hwclock': 'ハードウェア時計',
             '/usr/sbin/ntpdate': '時刻同期'}
    return f'{first} [引数・後続コマンド非表示]' if first in known else '[コマンド非表示]'


class CronCollector:
    name = 'cron'

    def __init__(self, path: Path, timezone: str):
        self.path, self.timezone = path, timezone

    def collect(self, now: datetime) -> Collection:
        result = Collection(collector=self.name, status='ok', message='', attempted_at=now)
        try:
            with self.path.open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('size limit')
            content = data.decode('utf-8')
        except PermissionError:
            return result.model_copy(update={'status': 'permission_denied', 'message': 'crontab の読み取り権限がありません'})
        except OSError:
            return result.model_copy(update={'status': 'unavailable', 'message': 'crontab を読み取れません。マウントを確認してください'})
        except (ValueError, UnicodeError):
            return result.model_copy(update={'status': 'parse_error', 'message': '入力サイズまたは文字コードが非対応です'})
        duplicates: Counter[str] = Counter()
        environment = tuple(f'{match[1]}={match[2]}' for raw in content.splitlines()
                            if (match := ENVIRONMENT_ASSIGNMENT.fullmatch(raw)))
        env_scope = 0
        context_id = cron_context_id(source=SOURCE_LOCATION, timezone=self.timezone, environment=environment)
        env_timezone = any(value.startswith(('TZ=', 'CRON_TZ=')) for value in environment)
        for number, raw in enumerate(content.splitlines(), 1):
            line = raw.lstrip(' \t')
            if not line.strip() or line.startswith('#'):
                continue
            if ENVIRONMENT_ASSIGNMENT.fullmatch(raw):
                env_scope += 1
                continue
            if len(result.tasks) >= MAX_TASKS:
                result.status = 'partial'
                result.message = '500件の上限を超えたため一部を取得していません'
                break
            parts = re.split(r'[ \t]+', line, maxsplit=5)
            expression = ' '.join(parts[:5]) if len(parts) >= 6 else '@unsupported'
            # Malformed rows may actually be commands containing credentials.
            # Retain only cron-shaped fields; never expose arbitrary raw text.
            token = r'(?:[0-9*,/\-]|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC|SUN|MON|TUE|WED|THU|FRI|SAT)+'
            if len(parts) != 6 or not parts[5] or not all(re.fullmatch(token, part, re.I) for part in parts[:5]):
                expression = '@unsupported'
            command = parts[5] if len(parts) >= 6 else line
            definition_id = cron_definition_id(context_id=context_id, scope=env_scope,
                expression=expression, command=command, raw_line=raw)
            duplicates[definition_id] += 1
            task = Task(id=f'{definition_id}-{duplicates[definition_id]}',
                        definition_id=definition_id, name=f'cron ジョブ（行 {number}）',
                        schedule=Schedule(expression=expression, timezone=self.timezone,
                                          description=describe(expression) if len(expression.split()) == 5 else '未対応の記法'),
                        source=Source(collector='cron', location=SOURCE_LOCATION), command=safe_command(command),
                        collected_at=now)
            if expression != '@unsupported':
                # Preserve the command from this snapshot, even if its cron
                # fields fail validation. Unseparable rows remain unavailable.
                task._raw_command = command
                task.command_available = True
            try:
                validate(expression)
                if env_timezone:
                    raise ValueError('TZ / CRON_TZ 指定があるため時刻計算を停止しました。実機調査が必要です')
                task.runs_per_active_day = runs_per_active_day(expression)
                task.next_runs = next_runs(expression, now)
                if not task.next_runs:
                    task.warnings.append('8年以内の実行予定を算出できません')
            except ValueError:
                task.collection_status = 'parse_error'
                task.warnings.append('不正・未対応のcron式、または未対応のタイムゾーン指定です')
                result.status = 'partial'
            result.tasks.append(task)
        for task in result.tasks:
            task.duplicate_count = duplicates[task.definition_id]
        result.message = result.message or f'{len(result.tasks)}件取得' + ('（解析できない設定あり）' if result.status == 'partial' else '')
        if not result.tasks and result.status == 'ok':
            result.status = 'empty'
        if result.status in ('ok', 'empty'):
            result.last_success_at = now
        return result
