"""Entirely synthetic BIFF source fixtures, including deliberately stale caches."""

import json
from pathlib import Path
from struct import pack

import pytest

from core.document import legacy_spreadsheets as reader


def synthetic_xls(path: Path, *, tokens: bytes | None = None, formula_range: str | None = None, extra: bytes = b'') -> None:
    def record(code, payload=b''):
        return pack('<HH', code, len(payload)) + payload
    def bof(kind):
        return record(0x0809, pack('<HHHHII', 0x0600, kind, 0, 1997, 0, 6))
    tokens = tokens if tokens is not None else b'\x1e\x02\x00\x1e\x03\x00\x03'
    range_record = b''
    if formula_range is not None:
        if formula_range == 'shared':
            range_record = record(0x04BC, pack('<HHBBxBH', 1, 1, 0, 0, 1, len(tokens)) + tokens)
        else:
            range_record = record(0x0221, pack('<HHBBHIH', 1, 1, 0, 0, 0, 0, len(tokens)) + tokens)
        tokens = b'\x01' + pack('<HH', 1, 0)
    sheets = []
    for hidden in (False, True):
        sheets.append(bof(0x10) + record(0x0200, pack('<IIHHH', 0, 2, 0, 2, 0))
            + record(0x0203, pack('<HHHd', 0, 0, 0, 1200.5))
            + record(0x0006, pack('<HHHdHIH', 1, 0, 0, 6.25, 0, 0, len(tokens)) + tokens + extra)
            + range_record
            + record(0x0208, pack('<HHHHHHI', 1, 0, 2, 255, 0, 0, 0x20))
            + record(0x007D, pack('<HHHHHH', 1, 1, 2048, 0, 1, 0))
            + record(0x00E5, pack('<HHHHH', 1, 0, 0, 0, 1)) + record(0x000A))
    prefix = (bof(5) + record(0x0022, pack('<H', 1))
              + record(0x041E, pack('<HHB', 164, 4, 0) + b'0.00')
              + record(0x00E0, pack('<HHHBBBBIIH', 0, 164, 0, 0, 0, 0, 0, 0, 0, 0)))
    def bounds(offset, hidden, name):
        return record(0x0085, pack('<IBBBB', offset, hidden, 0, len(name), 0) + name.encode())
    offset = len(prefix + bounds(0, 0, 'Budget') + bounds(0, 1, 'Hidden budget') + record(0x000A))
    path.write_bytes(prefix + bounds(offset, 0, 'Budget') + bounds(offset + len(sheets[0]), 1, 'Hidden budget')
                     + record(0x000A) + b''.join(sheets))


def test_original_xls_values_formulas_visibility_and_metadata_are_preserved(tmp_path):
    path = tmp_path / 'synthetic.xls'
    synthetic_xls(path)
    original = path.read_bytes()
    records = [json.loads(line) for line in reader.legacy_spreadsheet_text(path).splitlines()]
    assert records[0]['date_epoch'] == '1904'
    assert any(row.get('sheet') == 'Hidden budget' and row['visibility'] == 'hidden' for row in records)
    cell = next(row for row in records if row.get('cell') == 'A2')
    assert cell['value'] == 6.25  # Its original cache intentionally disagrees with 2+3.
    assert cell['formula'].replace('.0', '') == '2+3'
    assert cell['formula_tokens'] == '1e02001e030003'
    assert cell['number_format'] == '0.00'
    assert any(row.get('hidden_rows') == [2] and row['hidden_columns'] == [2] for row in records)
    assert any(row.get('merged_ranges') == ['A1:B1'] for row in records)
    assert path.read_bytes() == original


def test_undecodable_formulas_are_explicit_and_limits_fail_without_partial_success(tmp_path, monkeypatch):
    path = tmp_path / 'synthetic.xls'
    synthetic_xls(path, tokens=b'\xff', extra=b'\x01\x02')
    records = [json.loads(line) for line in reader.legacy_spreadsheet_text(path).splitlines()]
    cell = next(row for row in records if row.get('cell') == 'A2')
    assert cell['formula'] is None and cell['formula_tokens'] == 'ff'
    assert cell['formula_diagnostic'] and cell['value'] == 6.25
    assert cell['formula_extra'] == '0102'
    monkeypatch.setattr(reader, 'MAX_CELLS', 1)
    with pytest.raises(ValueError, match='limit'):
        reader.legacy_spreadsheet_text(path)
    monkeypatch.setattr(reader, 'MAX_CELLS', 200_000)
    monkeypatch.setattr(reader, 'MAX_TEXT', 10)
    with pytest.raises(ValueError, match='text limit'):
        reader.legacy_spreadsheet_text(path)


@pytest.mark.parametrize('kind', ['shared', 'array'])
def test_shared_and_array_formulas_keep_anchor_tokens_and_decoded_expression(tmp_path, kind):
    path = tmp_path / 'synthetic.xls'
    synthetic_xls(path, formula_range=kind)
    rows = [json.loads(line) for line in reader.legacy_spreadsheet_text(path).splitlines()]
    formula = next(row for row in rows if row.get('cell') == 'A2')
    assert formula['value'] == 6.25
    assert formula['formula'].replace('.0', '') == '2+3'
    assert formula['formula_tokens'] == '0101000000'
    assert formula['formula_range_tokens'] == '1e02001e030003'


@pytest.mark.asyncio
async def test_real_office_xls_conversion_and_worker_keep_source_evidence(tmp_path):
    from core.document import prepare_document
    from core.document.worker import _run
    # The native LibreOffice exporter, rather than our BIFF fixture writer, qualifies
    # the pinned reader against a real executable's generated workbook.
    csv = tmp_path / 'synthetic.csv'
    csv.write_text('Label,Value\nSynthetic total,1200.5\n', encoding='utf-8')
    _run(['soffice', f'-env:UserInstallation={(tmp_path / "lo-profile").as_uri()}', '--headless',
          '--convert-to', 'xls:MS Excel 97', '--outdir', str(tmp_path), str(csv)])
    source = tmp_path / 'synthetic.xls'
    original = source.read_bytes()
    result = await prepare_document(source, source.name, 'application/vnd.ms-excel', tmp_path / 'prepared')
    assert result.pages and result.structured_text
    rows = [json.loads(line) for line in result.structured_text.splitlines()]
    assert any(row.get('value') == 1200.5 for row in rows)
    assert source.read_bytes() == original
