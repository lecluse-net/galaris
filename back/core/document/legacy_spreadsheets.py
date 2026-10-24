"""Source evidence for BIFF5/8 XLS, without opening a calculation engine.

xlrd 2.0.2 exposes caches and formatting but discards cell formula tokens. This
adapter reads those bounded BIFF records from its original workbook stream and
uses xlrd's formula decoder. Undecodable tokens remain explicit evidence, never a
fabricated expression. Private stream access is confined to this pinned adapter.
"""

import io
import json
from pathlib import Path
from struct import unpack_from
from typing import Any

import xlrd  # type: ignore[import-untyped]
from xlrd.formula import FMLA_TYPE_ARRAY, FMLA_TYPE_CELL, FMLA_TYPE_SHARED, decompile_formula  # type: ignore[import-untyped]

from .spreadsheets import MAX_CELLS, MAX_EXPANDED, MAX_TEXT


def _formulas(book: Any, index: int) -> dict[tuple[int, int], dict[str, object]]:
    position = book._sh_abs_posn[index]
    end = book.base + book.stream_len
    memory = book.mem
    cells: dict[tuple[int, int], tuple[bytes, int]] = {}
    ranges: dict[tuple[int, int], tuple[bytes, int, int]] = {}
    while position < end:
        if position + 4 > end:
            raise ValueError("Truncated XLS record header")
        code, size = unpack_from("<HH", memory, position)
        position += 4
        if position + size > end:
            raise ValueError("Truncated XLS record")
        data = memory[position:position + size]
        position += size
        if code == 0x000A:
            break
        if code == 0x0006:
            if len(data) < 22:
                raise ValueError("Truncated XLS formula")
            row, column = unpack_from("<HH", data)
            length = unpack_from("<H", data, 20)[0]
            if length > len(data) - 22:
                raise ValueError("Truncated XLS formula tokens")
            cells[row, column] = (data[22:], length)
        elif code in (0x04BC, 0x0221):  # SHRFMLA and ARRAY
            offset = 10 if code == 0x04BC else 14
            if len(data) < offset:
                raise ValueError("Truncated XLS formula range")
            row, _, column, _ = unpack_from("<HHBB", data)
            length = unpack_from("<H", data, offset - 2)[0]
            if length > len(data) - offset:
                raise ValueError("Truncated XLS formula range tokens")
            ranges[row, column] = (data[offset:], length, FMLA_TYPE_SHARED if code == 0x04BC else FMLA_TYPE_ARRAY)
        if len(cells) + len(ranges) > MAX_CELLS:
            raise ValueError("Spreadsheet formula limit exceeded")
    result: dict[tuple[int, int], dict[str, object]] = {}
    for (row, column), (source, length) in cells.items():
        tokens, kind = source, FMLA_TYPE_CELL
        evidence: dict[str, object] = {"formula_tokens": source[:length].hex(), "formula": None}
        if len(source) > length:
            evidence["formula_extra"] = source[length:].hex()
        if source[:1] == b"\x01" and len(source) >= 5:
            anchor = unpack_from("<HH", source, 1)
            if anchor in ranges:
                tokens, length, kind = ranges[anchor]
                evidence["formula_range_tokens"] = tokens[:length].hex()
                if len(tokens) > length:
                    evidence["formula_range_extra"] = tokens[length:].hex()
        try:
            expression = decompile_formula(book, tokens, length, kind, browx=row, bcolx=column)
            if not expression or tokens[:1] == b"\x01":
                raise ValueError("Unresolved formula tokens")
            evidence["formula"] = str(expression)
        except Exception:
            evidence["formula_diagnostic"] = "Formula expression unavailable; original BIFF tokens retained; cached value not recalculated"
        result[row, column] = evidence
    return result


def legacy_spreadsheet_text(path: Path) -> str:
    if path.stat().st_size > MAX_EXPANDED:
        raise ValueError("Spreadsheet source exceeds limit")
    # xlrd is an untyped binary-format boundary. All its dynamic objects remain here.
    book: Any = xlrd.open_workbook(str(path), formatting_info=True, on_demand=True,
                                   ragged_rows=True, logfile=io.StringIO())
    parts: list[str] = []
    size = count = 0

    def emit(value: object) -> None:
        nonlocal size
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        size += len(text)
        if size > MAX_TEXT:
            raise ValueError("Spreadsheet evidence exceeds text limit")
        parts.append(text)

    try:
        if book.biff_version not in (50, 70, 80):
            raise ValueError("Structural XLS evidence requires BIFF5 or BIFF8")
        emit({"format": "xls", "biff_version": book.biff_version,
              "date_epoch": "1904" if book.datemode else "1900",
              "cached_values": "original source caches; not recalculated or guaranteed current"})
        for index in range(book.nsheets):
            sheet: Any = book.sheet_by_index(index)
            formulas = _formulas(book, index)
            emit({"sheet": sheet.name, "visibility": {0: "visible", 1: "hidden", 2: "veryHidden"}.get(sheet.visibility, "unknown")})
            for row in range(sheet.nrows):
                count += sheet.row_len(row)
                if count > MAX_CELLS:
                    raise ValueError("Spreadsheet cell limit exceeded")
                for column in range(sheet.row_len(row)):
                    cell: Any = sheet.cell(row, column)
                    formula = formulas.get((row, column), {})
                    if cell.ctype == 0 and not formula:
                        continue
                    xf: Any = book.xf_list[cell.xf_index]
                    fmt: Any = book.format_map.get(xf.format_key)
                    emit({"cell": xlrd.cellname(row, column), "value": cell.value,
                          "type": cell.ctype, "number_format": fmt.format_str if fmt else None,
                          **formula})
            emit({"merged_ranges": [xlrd.cellname(rlo, clo) + ":" + xlrd.cellname(rhi-1, chi-1)
                                     for rlo, rhi, clo, chi in sheet.merged_cells],
                  "hidden_rows": [row + 1 for row, info in sheet.rowinfo_map.items() if info.hidden],
                  "hidden_columns": [column + 1 for column, info in sheet.colinfo_map.items() if info.hidden]})
            for (row, column), note in sheet.cell_note_map.items():
                emit({"cell": xlrd.cellname(row, column), "comment": note.text, "author": note.author})
            book.unload_sheet(index)
        return "\n".join(parts)
    finally:
        book.release_resources()
