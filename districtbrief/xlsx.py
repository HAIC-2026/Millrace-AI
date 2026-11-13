"""Read-only, stdlib-only reader for raw cell values in .xlsx workbooks.

Used to show staff the retained raw workbook cells behind published statistics.
Only zipfile and xml.etree.ElementTree are used. The file is opened for reading
only and nothing is written anywhere.

What is returned: the stored value as text. For shared strings and inline
strings that is the resolved text; for everything else it is the raw <v> text.
Number formats are not applied, so a cell that Excel displays as "8,619" may come
back as "8,619" (stored string) or "8619" (stored number). Callers normalize.

Limits:
- Sheet names are matched exactly (case-sensitive) against workbook.xml.
- Phonetic guide text (<rPh>) is excluded from strings, as Excel does not display it.
- Worksheets are streamed with iterparse and parsing stops once every requested
  reference has been seen. The workbook part and the shared string table are small
  and are parsed whole (the shared string table only when a requested cell needs it).
"""

from __future__ import annotations

import functools
import os
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib

__all__ = ["XlsxError", "read_cells"]

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

_M = "{%s}" % NS_MAIN
_PKG_REL = "{%s}" % NS_PKG_REL
_R_ID = "{%s}id" % NS_REL

_WORKBOOK_PART = "xl/workbook.xml"
_WORKBOOK_RELS_PART = "xl/_rels/workbook.xml.rels"
_WORKSHEET_REL_SUFFIX = "/worksheet"
_SHARED_STRINGS_REL_SUFFIX = "/sharedStrings"

# Used with fullmatch(), so no trailing-newline loophole that '$' would allow.
_REF_RE = re.compile(r"[A-Z]{1,3}[1-9][0-9]{0,6}")

_SHARED_STRINGS_CACHE_SIZE = 8


class XlsxError(Exception):
    """A workbook cannot be read, or a request is invalid (unknown sheet, bad ref)."""


def read_cells(path: str, sheet_name: str, refs: list[str]) -> dict[str, str | None]:
    """Return {ref: cell_text} for the requested A1-style refs on one sheet.

    ``cell_text`` is the stored value as text (see module docstring). Missing or
    empty cells map to None. Raises XlsxError for an unknown sheet name, a malformed
    ref, a file that is not a readable .xlsx zip, or corrupt workbook XML.
    """
    wanted = _validate_refs(refs)
    path = os.fspath(path)
    label = os.path.basename(path) or path

    try:
        with open(path, "rb") as fh, zipfile.ZipFile(fh, "r") as zf:
            sheets, rels = _read_workbook(zf, label)
            sheet_part = _find_sheet_part(sheets, rels, sheet_name, label)
            found = _scan_worksheet(zf, sheet_part, wanted, label)

            needs_shared = any(raw is not None and raw[0] == "s" and raw[1] is not None
                               for raw in found.values())
            shared: tuple[str, ...] = ()
            if needs_shared:
                sst_part = _find_shared_strings_part(rels)
                if sst_part is None:
                    raise XlsxError(f"{label} has shared-string cells but no shared string table")
                shared = _shared_strings(path, sst_part)
    except XlsxError:
        raise
    except zipfile.BadZipFile as exc:
        raise XlsxError(f"{label} is not a valid .xlsx (zip) file") from exc
    except ET.ParseError as exc:
        raise XlsxError(f"{label} contains malformed XML") from exc
    except (zlib.error, NotImplementedError, RuntimeError, EOFError) as exc:
        raise XlsxError(f"{label} could not be decompressed: {exc}") from exc
    except OSError as exc:
        raise XlsxError(f"cannot read {label}: {exc.strerror or exc}") from exc

    return {ref: _cell_text(found.get(ref), shared, label) for ref in wanted}


def _validate_refs(refs: list[str]) -> list[str]:
    if isinstance(refs, (str, bytes)):
        raise XlsxError("refs must be a list of A1-style references, not a single string")
    try:
        items = list(refs)
    except TypeError as exc:
        raise XlsxError("refs must be a list of A1-style references") from exc
    for ref in items:
        if not isinstance(ref, str) or _REF_RE.fullmatch(ref) is None:
            raise XlsxError(f"malformed cell reference: {ref!r}")
    return list(dict.fromkeys(items))  # de-duplicate, keep request order


def _parse_part(zf: zipfile.ZipFile, part: str, label: str) -> ET.Element:
    try:
        data = zf.read(part)
    except KeyError:
        raise XlsxError(f"{label} has no {part}; it is not an .xlsx workbook") from None
    return ET.fromstring(data)


def _resolve_target(base_dir: str, target: str) -> str:
    """Resolve a relationship Target to a zip member name.

    Targets are relative to the source part's directory (e.g. 'worksheets/sheet1.xml'
    relative to 'xl/'), or absolute from the package root ('/xl/worksheets/sheet1.xml').
    """
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(base_dir, target))


def _read_workbook(zf: zipfile.ZipFile, label: str):
    """Return ([(sheet_name, r:id)], {rId: (rel_type, resolved_part)})."""
    wb = _parse_part(zf, _WORKBOOK_PART, label)
    sheets: list[tuple[str, str | None]] = []
    sheets_el = wb.find(_M + "sheets")
    if sheets_el is not None:
        for sheet in sheets_el.findall(_M + "sheet"):
            sheets.append((sheet.get("name", ""), sheet.get(_R_ID)))

    rels_root = _parse_part(zf, _WORKBOOK_RELS_PART, label)
    rels: dict[str, tuple[str, str]] = {}
    for rel in rels_root.iter(_PKG_REL + "Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        rel_id = rel.get("Id")
        if rel_id is None:
            continue
        rels[rel_id] = (rel.get("Type", ""), _resolve_target("xl", rel.get("Target", "")))
    return sheets, rels


def _find_sheet_part(sheets, rels, sheet_name: str, label: str) -> str:
    for name, rel_id in sheets:
        if name == sheet_name:
            rel = rels.get(rel_id) if rel_id is not None else None
            if rel is None or not rel[0].endswith(_WORKSHEET_REL_SUFFIX):
                raise XlsxError(f"sheet {sheet_name!r} in {label} is not a worksheet")
            return rel[1]
    names = ", ".join(name for name, _ in sheets) or "none"
    raise XlsxError(f"no sheet named {sheet_name!r} in {label} (sheets: {names})")


def _find_shared_strings_part(rels) -> str | None:
    for rel_type, part in rels.values():
        if rel_type.endswith(_SHARED_STRINGS_REL_SUFFIX):
            return part
    return None


def _si_text(node: ET.Element) -> str:
    """Concatenate the text of an <si> or <is> item, including rich-text runs.

    Phonetic runs (<rPh>) are skipped; they are not part of the displayed text.
    """
    chunks: list[str] = []
    for child in node:
        if child.tag == _M + "t":
            chunks.append(child.text or "")
        elif child.tag == _M + "r":
            for t in child.findall(_M + "t"):
                chunks.append(t.text or "")
    return "".join(chunks)


def _raw_cell(elem: ET.Element) -> tuple[str, str | None, str | None]:
    """Snapshot one <c> element as (type, raw <v> text, resolved inline text)."""
    v_el = elem.find(_M + "v")
    is_el = elem.find(_M + "is")
    return (
        elem.get("t", "n"),
        v_el.text if v_el is not None else None,
        _si_text(is_el) if is_el is not None else None,
    )


def _scan_worksheet(zf: zipfile.ZipFile, part: str, wanted: list[str], label: str):
    """Stream one worksheet and return {ref: raw_cell} for the wanted refs found."""
    try:
        stream = zf.open(part)
    except KeyError:
        raise XlsxError(f"{label} has no worksheet part {part}") from None

    found: dict[str, tuple[str, str | None, str | None]] = {}
    remaining = set(wanted)
    if not remaining:
        stream.close()
        return found
    with stream:
        for event, elem in ET.iterparse(stream, events=("end",)):
            if elem.tag == _M + "c":
                ref = elem.get("r")
                if ref in remaining:
                    found[ref] = _raw_cell(elem)
                    remaining.discard(ref)
                    if not remaining:
                        break
            elif elem.tag == _M + "row":
                # Cells belong to their row; drop the row once it has been seen.
                elem.clear()
    return found


def _cell_text(raw, shared: tuple[str, ...], label: str) -> str | None:
    if raw is None:
        return None
    cell_type, v_text, inline = raw
    if cell_type == "inlineStr":
        text = inline
    elif cell_type == "s":
        if v_text is None:
            return None
        text = shared[_shared_index(v_text, len(shared), label)]
    else:
        text = v_text
    return text or None  # empty string counts as an empty cell


def _shared_index(v_text: str, count: int, label: str) -> int:
    try:
        index = int(v_text.strip())
    except ValueError:
        raise XlsxError(f"{label} has a non-numeric shared string index {v_text!r}") from None
    if not 0 <= index < count:
        raise XlsxError(f"{label} references shared string {index}, but the table has {count}")
    return index


def _shared_strings(path: str, part: str) -> tuple[str, ...]:
    """Return the shared string table, cached by (abs path, mtime, size, part)."""
    st = os.stat(path)
    return _cached_shared_strings(os.path.abspath(path), st.st_mtime_ns, st.st_size, part)


@functools.lru_cache(maxsize=_SHARED_STRINGS_CACHE_SIZE)
def _cached_shared_strings(abs_path: str, mtime_ns: int, size: int, part: str) -> tuple[str, ...]:
    # The cache key includes mtime and size, so a rewritten file is re-read.
    # Results are tuples so callers cannot mutate what is cached.
    label = os.path.basename(abs_path)
    with open(abs_path, "rb") as fh, zipfile.ZipFile(fh, "r") as zf:
        root = _parse_part(zf, part, label)
    return tuple(_si_text(si) for si in root.iter(_M + "si"))
