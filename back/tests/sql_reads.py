"""Capture real SQL reads for bounded-query workflow regressions."""

from contextlib import asynccontextmanager
import time

from sqlalchemy import event


class SQLReads(list):
    def __init__(self):
        super().__init__()
        self.result_columns = set()


@asynccontextmanager
async def measured_reads(db, label):
    connection = await db.connection()
    statements = SQLReads()

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)

    def results(_connection, cursor, _statement, _parameters, _context, _many):
        if cursor.description:
            statements.result_columns.update(column[0] for column in cursor.description)

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    event.listen(connection.sync_connection, "after_cursor_execute", results)
    started = time.perf_counter()
    try:
        yield statements
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
        event.remove(connection.sync_connection, "after_cursor_execute", results)
        print(f"SQL_READS {label}: queries={len(statements)} seconds={time.perf_counter() - started:.6f}")
