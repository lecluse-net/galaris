"""Volume guarantees: history size never forces full-calendar read parsing."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

import pytest
from sqlalchemy import event as sql_event
from app.calendar import ical, service, store, calculation


def synthetic_calendar(count, *, dense=False):
    base = datetime(2026,1,1,10,tzinfo=timezone.utc) if dense else datetime(2020,1,1,10,tzinfo=timezone.utc)
    components = []
    for index in range(count):
        start = base + (timedelta(minutes=index * 20) if dense else timedelta(days=index % 3650))
        finish = start + timedelta(minutes=30)
        components.append(f'BEGIN:VEVENT\r\nUID:{"dense" if dense else "sparse"}-{index}@example.test\r\nDTSTAMP:20200101T000000Z\r\nDTSTART:{start:%Y%m%dT%H%M%SZ}\r\nDTEND:{finish:%Y%m%dT%H%M%SZ}\r\nSUMMARY:Synthetic appointment {index}\r\nDESCRIPTION:Synthetic load data\r\nEND:VEVENT\r\n')
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + ''.join(components) + 'END:VCALENDAR\r\n').encode()


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [10000, 100000])
async def test_large_agendas_use_indexed_local_windows_and_dense_month_is_complete(db, agent, personal, monkeypatch, count):
    _, feed = personal
    started = perf_counter()
    resources = await asyncio.to_thread(ical.split_resources, synthetic_calendar(count))
    for index in range(0,len(resources),200):
        rows = await store.import_new_resources(feed, resources[index:index+200])
        await store.project_events(feed, rows, agent_id=agent.id)
    await db.commit()
    imported_ms = (perf_counter() - started) * 1000
    lower = datetime(2026,1,1,tzinfo=timezone.utc)
    upper = datetime(2026,2,1,tzinfo=timezone.utc)
    expected = sum(lower <= datetime(2020,1,1,10,tzinfo=timezone.utc) + timedelta(days=index % 3650) < upper for index in range(count))
    queries = []
    query_profiles = []
    def observed(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)
        context._calendar_query_started = perf_counter()
    def completed(connection, cursor, statement, parameters, context, executemany):
        query_profiles.append(dict(milliseconds=round((perf_counter() - context._calendar_query_started) * 1000, 2),
            statement=statement, parameters=parameters))
    engine = db.bind.sync_engine
    sql_event.listen(engine, 'before_cursor_execute', observed)
    sql_event.listen(engine, 'after_cursor_execute', completed)
    try:
        samples = []
        for _ in range(3):
            started = perf_counter()
            window = await service.event_window(agent.id, lower, upper)
            samples.append(round((perf_counter()-started)*1000, 2))
            assert window.total == len(window.items) == expected
        assert len(queries) <= 18
    finally:
        sql_event.remove(engine, 'before_cursor_execute', observed)
        sql_event.remove(engine, 'after_cursor_execute', completed)
    plans = []
    connection = await db.connection()
    for profile in query_profiles[:6]:
        if not profile['statement'].lstrip().upper().startswith('SELECT'):
            continue
        plan = await connection.exec_driver_sql('EXPLAIN (ANALYZE, FORMAT JSON) ' + profile['statement'], profile['parameters'])
        plans.append(plan.scalar())
    def event_rows_examined(node):
        own = 0
        if node.get('Relation Name') == 'calendar_events':
            own = (node.get('Actual Rows', 0) + node.get('Rows Removed by Filter', 0)
                + node.get('Rows Removed by Index Recheck', 0)) * node.get('Actual Loops', 1)
        return own + sum(event_rows_examined(child) for child in node.get('Plans', []))
    # A monthly window must not scan the full event history per occurrence,
    # including immediately after bulk import, before ANALYZE has good statistics.
    examined = [event_rows_examined(plan[0]['Plan']) for plan in plans]
    assert max(examined, default=0) <= expected * 2 + 10
    dense = await asyncio.to_thread(ical.split_resources, synthetic_calendar(1500,dense=True))
    for index in range(0,len(dense),200):
        rows = await store.import_new_resources(feed, dense[index:index+200])
        await store.project_events(feed, rows, agent_id=agent.id)
    await db.commit()
    def unexpected(*args, **kwargs):
        raise AssertionError('A warm SQL window must not parse calendar source content')
    monkeypatch.setattr(ical, 'parse_calendar', unexpected)
    monkeypatch.setattr(calculation, 'events_between', unexpected)
    window = await service.event_window(agent.id, lower, upper)
    assert window.total == len(window.items) == expected + 1500
    report = dict(total_events=count, visible_events=expected, import_ms=round(imported_ms,2),
        window_samples_ms=samples, queries_for_three_windows=len(queries), dense_month_events=window.total,
        query_profiles=query_profiles, query_plans=plans, event_rows_examined=examined)
    directory = Path('../artifacts')
    directory.mkdir(exist_ok=True)
    (directory / f'calendar-backend-benchmark-{count}.json').write_text(json.dumps(report,indent=2,default=str))
