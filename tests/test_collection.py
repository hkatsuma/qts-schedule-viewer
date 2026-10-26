import asyncio
from src.services.collection import CollectionService


class BrokenCollector:
    timezone = 'UTC'

    def collect(self, now):
        raise RuntimeError('SECRET')


def test_error_isolation():
    service = CollectionService(BrokenCollector())
    asyncio.run(service.refresh())
    assert service.results['cron'].status == 'parse_error'
    assert 'SECRET' not in service.results['cron'].model_dump_json()
    assert service.results['hbs'].status == 'unsupported'
