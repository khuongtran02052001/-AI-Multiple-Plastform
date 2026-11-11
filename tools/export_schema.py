"""Export an idempotent Supabase bootstrap script from the application's tables.

This only writes a local SQL file. It never connects to a database.
"""
from pathlib import Path
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects import postgresql
from app.db import metadata


def export_schema():
    statements = [
        '-- khuoqtd Publisher: backend-only tables; no browser/Data API grants.',
        '-- Run only in the selected project SQL Editor, or let app startup create tables.',
        '-- Existing tables are not altered to repair an incompatible schema.',
        'BEGIN;', 'SET LOCAL search_path = public;',
    ]
    dialect = postgresql.dialect()
    for table in metadata.sorted_tables:
        statements.append(str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).strip() + ';')
    for table in metadata.sorted_tables:
        for index in sorted(table.indexes, key=lambda item: item.name):
            statements.append(str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect)).strip() + ';')
        statements.append(f'ALTER TABLE public.{table.name} ENABLE ROW LEVEL SECURITY;')
        statements.append(f'REVOKE ALL ON public.{table.name} FROM PUBLIC, anon, authenticated;')
    statements.append('COMMIT;')
    return '\n\n'.join(statements) + '\n'


if __name__ == '__main__':
    target = Path(__file__).resolve().parents[1] / 'deploy' / 'supabase-bootstrap.sql'
    target.write_text(export_schema())
    print('Wrote deploy/supabase-bootstrap.sql. No remote database was changed.')
