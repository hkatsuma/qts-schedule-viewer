"""Versioned identities for cron definitions, without shell interpretation."""
import hashlib
import json


def _digest(payload: list) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def cron_context_id(*, source: str, timezone: str, environment: tuple[str, ...]) -> str:
    # Hash once per collection, rather than copying a potentially large
    # environment declaration list into the payload for every task.
    return _digest(['cron-context-v1', source, timezone, environment])


def cron_definition_id(*, context_id: str, scope: int,
                       expression: str, command: str, raw_line: str) -> str:
    # An unsupported row is opaque: never infer a command or strip comments.
    definition = (['opaque', raw_line] if expression == '@unsupported'
                  else ['standard', expression.split(), command])
    # All environment declarations are included conservatively. The prefix
    # length distinguishes identical rows across environment boundaries without
    # claiming to reproduce QTS's environment/expansion semantics.
    return 'cron-v1-' + _digest(['cron-v1', context_id, scope, definition])
