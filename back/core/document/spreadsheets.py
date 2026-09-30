"""Bounded source-level spreadsheet evidence, independent of printed pagination."""

import json
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

MAX_EXPANDED = 512 * 1024 * 1024
MAX_CELLS = 200_000
MAX_TEXT = 10_000_000


def spreadsheet_text(path: Path) -> str:
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 20_000 or sum(e.file_size for e in entries) > MAX_EXPANDED:
            raise ValueError("Expanded spreadsheet exceeds limit")

        def xml(name: str) -> ET.Element:
            data = archive.read(name)
            if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                raise ValueError("Document XML entities are not supported")
            return ET.fromstring(data)

        parts: list[str] = []
        count = 0
        size = 0

        def emit(value: object) -> None:
            nonlocal size
            text = json.dumps(value, ensure_ascii=False)
            size += len(text)
            if size > MAX_TEXT:
                raise ValueError("Spreadsheet evidence exceeds text limit")
            parts.append(text)

        if "xl/workbook.xml" in archive.namelist():
            workbook = xml("xl/workbook.xml")
            properties = workbook.find("{*}workbookPr")
            emit({"date_epoch": "1904" if properties is not None and properties.get("date1904") in {"1", "true"} else "1900",
                  "cached_values": "source caches; not recalculated or guaranteed current"})
            shared = ["".join(s.itertext()) for s in xml("xl/sharedStrings.xml")] if "xl/sharedStrings.xml" in archive.namelist() else []
            relationships = {r.get("Id", ""): r.get("Target", "") for r in xml("xl/_rels/workbook.xml.rels")}
            formats: dict[str, str] = {}
            styles: list[str] = []
            if "xl/styles.xml" in archive.namelist():
                root = xml("xl/styles.xml")
                formats = {f.get("numFmtId", ""): f.get("formatCode", "") for f in root.findall(".//{*}numFmt")}
                xfs = root.find("{*}cellXfs")
                styles = [xf.get("numFmtId", "0") for xf in xfs] if xfs is not None else []
            for sheet in workbook.findall(".//{*}sheet"):
                relation = next((v for k, v in sheet.attrib.items() if k.endswith("}id")), "")
                target = relationships.get(relation, "")
                member = target.lstrip("/") if target.startswith("/") else "xl/" + target
                if ".." in PurePosixPath(member).parts or member not in archive.namelist():
                    raise ValueError("Invalid spreadsheet sheet relationship")
                root = xml(member)
                emit({"sheet": sheet.get("name"), "visibility": sheet.get("state", "visible"), "source": member})
                for cell in root.findall(".//{*}c"):
                    count += 1
                    if count > MAX_CELLS:
                        raise ValueError("Spreadsheet cell limit exceeded")
                    value = cell.findtext("{*}v", default="")
                    kind = cell.get("t", "n")
                    if kind == "s" and value:
                        value = shared[int(value)]
                    elif kind == "inlineStr":
                        inline = cell.find("{*}is")
                        value = "".join(inline.itertext()) if inline is not None else ""
                    style = int(cell.get("s", "0"))
                    format_id = styles[style] if style < len(styles) else "0"
                    formula = cell.find("{*}f")
                    emit({"cell": cell.get("r"), "value": value, "type": kind,
                          "formula": formula.text if formula is not None else None,
                          "formula_attributes": formula.attrib if formula is not None else {},
                          "number_format_id": format_id, "number_format": formats.get(format_id, "builtin:" + format_id)})
                emit({"merged_ranges": [r.get("ref") for r in root.findall(".//{*}mergeCell")],
                      "hidden_rows": [r.get("r") for r in root.findall(".//{*}row") if r.get("hidden") in {"1", "true"}],
                      "hidden_columns": [c.attrib for c in root.findall(".//{*}col") if c.get("hidden") in {"1", "true"}]})
            for member in archive.namelist():
                if member.startswith("xl/comments") and member.endswith(".xml"):
                    root = xml(member)
                    authors = [a.text or "" for a in root.findall(".//{*}author")]
                    for comment in root.findall(".//{*}comment"):
                        emit({"comments_source": member, "cell": comment.get("ref"), "author_index": comment.get("authorId"),
                              "authors": authors, "comment": "".join(comment.itertext())})
        elif "content.xml" in archive.namelist():
            root = xml("content.xml")
            def attr(element: ET.Element, name: str, default: str = "") -> str:
                return next((v for k, v in element.attrib.items() if k.endswith("}" + name)), default)
            for sheet in root.findall(".//{*}table"):
                emit({"sheet": attr(sheet, "name"), "style": attr(sheet, "style-name")})
                row_number = 1
                for row in sheet.findall("{*}table-row"):
                    repeat = int(attr(row, "number-rows-repeated", "1"))
                    cells: list[dict[str, object]] = []
                    column = 1
                    for cell in row:
                        columns = int(attr(cell, "number-columns-repeated", "1"))
                        text = " ".join("".join(p.itertext()) for p in cell.findall("{*}p"))
                        formula = attr(cell, "formula")
                        value = attr(cell, "value") or attr(cell, "date-value") or attr(cell, "boolean-value")
                        if text or value or formula:
                            count += 1
                            if count > MAX_CELLS:
                                raise ValueError("Spreadsheet cell limit exceeded")
                            cells.append({"column": column, "columns_repeated": columns, "display_text": text,
                                          "value": value, "type": attr(cell, "value-type"), "formula": formula,
                                          "style": attr(cell, "style-name"), "column_span": attr(cell, "number-columns-spanned"),
                                          "row_span": attr(cell, "number-rows-spanned"),
                                          "comments": ["".join(a.itertext()) for a in cell.findall("{*}annotation")]})
                        column += columns
                    if cells:
                        emit({"row": row_number, "rows_repeated": repeat, "visibility": attr(row, "visibility", "visible"), "cells": cells})
                    row_number += repeat
            for member in ("styles.xml",):
                if member in archive.namelist():
                    for style in xml(member).findall(".//{*}style"):
                        emit({"style_definition": style.attrib, "properties": [p.attrib for p in style]})
        else:
            raise ValueError("Unsupported spreadsheet container")
        return "\n".join(parts)
