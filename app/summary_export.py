from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="无课汇总" sheetId="1" r:id="rId1"/>
    <sheet name="总无课表" sheetId="2" r:id="rId3"/>
  </sheets>
</workbook>
"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>
"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="4">
    <font><sz val="10"/><name val="Microsoft YaHei"/></font>
    <font><b/><sz val="16"/><color rgb="FFFFFFFF"/><name val="Microsoft YaHei"/></font>
    <font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Microsoft YaHei"/></font>
    <font><b/><sz val="10"/><color rgb="FF26302D"/><name val="Microsoft YaHei"/></font>
  </fonts>
  <fills count="7">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF8B1E26"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE5F1ED"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFE8C2"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF176B5B"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF1EFE9"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFD9D5CB"/></left>
      <right style="thin"><color rgb="FFD9D5CB"/></right>
      <top style="thin"><color rgb="FFD9D5CB"/></top>
      <bottom style="thin"><color rgb="FFD9D5CB"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="11">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="6" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="3" fillId="6" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="top" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="top" wrapText="1"/></xf>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
</styleSheet>
"""

CORE_PROPERTIES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:dcterms="http://purl.org/dc/terms/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>无课汇总表</dc:title>
  <dc:creator>科创实践中心管理系统</dc:creator>
</cp:coreProperties>
"""

APP_PROPERTIES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
  xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>科创实践中心管理系统</Application>
</Properties>
"""


def _column_name(index):
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell(reference, value, style=0, numeric=False):
    if value is None:
        return f'<c r="{reference}" s="{style}"/>'
    if numeric:
        return f'<c r="{reference}" s="{style}"><v>{value}</v></c>'
    return (
        f'<c r="{reference}" t="inlineStr" s="{style}">'
        f'<is><t xml:space="preserve">{escape(str(value))}</t></is></c>'
    )


def _row(number, cells, height=None):
    attributes = f' r="{number}"'
    if height:
        attributes += f' ht="{height}" customHeight="1"'
    return f"<row{attributes}>{''.join(cells)}</row>"


def build_total_free_sheet_xml(summary):
    weekdays = summary["weekdays"]
    table_rows = summary.get("free_table_rows") or []
    last_column_name = _column_name(2 + len(weekdays))
    rows = [
        _row(
            1,
            [_cell("A1", "总无课表", 1)],
            height=30,
        ),
        _row(
            2,
            [
                _cell(
                    "A2",
                    (
                        f"{summary['department_label']} · 第 {summary['week_number']} 周"
                        f" · 每个时段无课成员名单"
                    ),
                    8,
                )
            ],
            height=22,
        ),
        _row(
            3,
            [
                _cell("A3", "节次", 2),
                _cell("B3", "时间", 2),
                _cell("C3", "星期", 2),
            ],
            height=24,
        ),
        _row(
            4,
            [
                _cell("A4", "", 2),
                _cell("B4", "", 2),
                *[
                    _cell(f"{_column_name(3 + index)}4", weekday, 2)
                    for index, weekday in enumerate(weekdays)
                ],
            ],
            height=22,
        ),
    ]

    current_row = 5
    for row_data in table_rows:
        cells = [
            _cell(f"A{current_row}", f"{row_data['label']}节", 3),
            _cell(f"B{current_row}", row_data.get("time_range") or "", 3),
        ]
        for column_index, cell in enumerate(row_data.get("cells") or []):
            free_names = [
                member["name"] for member in cell.get("free_students", [])
            ]
            name_text = "\n".join(free_names) if free_names else "无"
            style = 10 if cell.get("all_free") else 9
            cells.append(
                _cell(
                    f"{_column_name(3 + column_index)}{current_row}",
                    name_text,
                    style,
                )
            )
        max_names = max(
            (
                len(cell.get("free_students") or [])
                for cell in row_data.get("cells") or []
            ),
            default=0,
        )
        row_height = min(max(30, 16 + max_names * 15), 409)
        rows.append(
            _row(
                current_row,
                cells,
                height=row_height,
            )
        )
        current_row += 1

    last_row = max(current_row - 1, 4)
    sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:{last_column_name}{last_row}"/>
  <sheetViews>
    <sheetView showGridLines="0">
      <pane xSplit="2" ySplit="4" topLeftCell="C5" activePane="bottomRight" state="frozen"/>
      <selection pane="bottomRight" activeCell="C5" sqref="C5"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>
    <col min="1" max="1" width="10" customWidth="1"/>
    <col min="2" max="2" width="16" customWidth="1"/>
    <col min="3" max="{2 + len(weekdays)}" width="28" customWidth="1"/>
  </cols>
  <sheetData>{''.join(rows)}</sheetData>
  <mergeCells count="5">
    <mergeCell ref="A1:{last_column_name}1"/>
    <mergeCell ref="A2:{last_column_name}2"/>
    <mergeCell ref="A3:A4"/>
    <mergeCell ref="B3:B4"/>
    <mergeCell ref="C3:{last_column_name}3"/>
  </mergeCells>
  <pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
  <pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>
</worksheet>
"""
    return sheet_xml


def build_total_free_xlsx(summary):
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="总无课表" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("docProps/core.xml", CORE_PROPERTIES)
        archive.writestr("docProps/app.xml", APP_PROPERTIES)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", STYLES)
        archive.writestr(
            "xl/worksheets/sheet1.xml", build_total_free_sheet_xml(summary)
        )
    return buffer.getvalue()


def build_availability_summary_xlsx(summary):
    slots = summary["time_slots"]
    member_cells = [member["cells"] for member in summary["members"]]
    all_free = summary["all_free"]

    metadata_columns = 3
    slot_count = len(slots)
    free_count_column = metadata_columns + slot_count + 1
    last_column = free_count_column
    last_column_name = _column_name(last_column)
    header_row = 3
    data_start_row = 5
    merges = [
        f"A1:{last_column_name}1",
        f"A2:{last_column_name}2",
        "A3:A4",
        "B3:B4",
        "C3:C4",
        f"{_column_name(free_count_column)}3:{_column_name(free_count_column)}4",
    ]

    rows = [
        _row(
            1,
            [
                _cell("A1", "部门成员无课汇总表", 1)
            ],
            height=30,
        ),
        _row(
            2,
            [
                _cell(
                    "A2",
                    (
                        f"{summary['department_label']} · 第 {summary['week_number']} 周"
                        f" · 成员 {summary['member_count']} 人"
                        f" · 全员无课时段 {summary['all_free_count']} 个"
                    ),
                    8,
                )
            ],
            height=22,
        ),
    ]

    header_cells = [
        _cell("A3", "序号", 3),
        _cell("B3", "姓名", 3),
        _cell("C3", "学号/工号", 3),
    ]
    for weekday_index, weekday_label in enumerate(summary["weekdays"]):
        start_column = metadata_columns + weekday_index * len(summary["periods"]) + 1
        end_column = start_column + len(summary["periods"]) - 1
        start_name = _column_name(start_column)
        end_name = _column_name(end_column)
        header_cells.append(_cell(f"{start_name}3", weekday_label, 2))
        merges.append(f"{start_name}3:{end_name}3")
    header_cells.append(
        _cell(f"{_column_name(free_count_column)}3", "无课节数", 3)
    )
    rows.append(_row(header_row, header_cells, height=24))

    period_cells = ["", "", ""]
    for _weekday in summary["weekdays"]:
        period_cells.extend(str(period) for period in summary["periods"])
    period_cells.append("")
    rows.append(
        _row(
            4,
            [
                _cell(f"{_column_name(index + 1)}4", value, 3)
                for index, value in enumerate(period_cells)
            ],
            height=20,
        )
    )

    current_row = data_start_row
    for member_index, member in enumerate(summary["members"], start=1):
        cells = [
            _cell(f"A{current_row}", member_index, 8, numeric=True),
            _cell(f"B{current_row}", member["name"], 6),
            _cell(f"C{current_row}", member["student_id"] or "", 6),
        ]
        for column_index, cell in enumerate(member_cells[member_index - 1]):
            column_number = metadata_columns + column_index + 1
            reference = f"{_column_name(column_number)}{current_row}"
            if cell["free"]:
                cells.append(_cell(reference, "无课", 4))
            else:
                cells.append(_cell(reference, "\n".join(cell["courses"]), 5))
        cells.append(
            _cell(
                f"{_column_name(free_count_column)}{current_row}",
                member["free_count"],
                8,
                numeric=True,
            )
        )
        rows.append(_row(current_row, cells, height=26))
        current_row += 1

    all_free_cells = [
        _cell(f"A{current_row}", "全员无课", 7),
        _cell(f"B{current_row}", "", 7),
        _cell(f"C{current_row}", "", 7),
    ]
    for column_index, is_free in enumerate(all_free):
        column_number = metadata_columns + column_index + 1
        reference = f"{_column_name(column_number)}{current_row}"
        all_free_cells.append(
            _cell(reference, "全员无课" if is_free else "", 7)
        )
    all_free_cells.append(
        _cell(
            f"{_column_name(free_count_column)}{current_row}",
            summary["all_free_count"],
            7,
            numeric=True,
        )
    )
    rows.append(_row(current_row, all_free_cells, height=24))
    last_row = current_row

    column_widths = [
        (1, 1, 6),
        (2, 2, 14),
        (3, 3, 16),
        (4, 3 + slot_count, 11),
        (free_count_column, free_count_column, 12),
    ]
    columns_xml = "".join(
        (
            f'<col min="{start}" max="{end}" width="{width}" '
            'customWidth="1"/>'
        )
        for start, end, width in column_widths
    )
    merge_xml = "".join(f'<mergeCell ref="{reference}"/>' for reference in merges)
    dimension = f"A1:{last_column_name}{last_row}"
    sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="{dimension}"/>
  <sheetViews>
    <sheetView showGridLines="0" tabSelected="1">
      <pane xSplit="3" ySplit="4" topLeftCell="D5" activePane="bottomRight" state="frozen"/>
      <selection pane="bottomRight" activeCell="D5" sqref="D5"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>{columns_xml}</cols>
  <sheetData>{''.join(rows)}</sheetData>
  <mergeCells count="{len(merges)}">{merge_xml}</mergeCells>
  <pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
  <pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>
</worksheet>
"""

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("docProps/core.xml", CORE_PROPERTIES)
        archive.writestr("docProps/app.xml", APP_PROPERTIES)
        archive.writestr("xl/workbook.xml", WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        archive.writestr("xl/styles.xml", STYLES)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr(
            "xl/worksheets/sheet2.xml", build_total_free_sheet_xml(summary)
        )
    return buffer.getvalue()
