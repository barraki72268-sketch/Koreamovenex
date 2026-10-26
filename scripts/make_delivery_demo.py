"""Build synthetic workbooks for testing the Excel UI; no company measurements."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape
import argparse
import numpy as np


def make_workbook(path, profile):
    rng = np.random.default_rng(42)
    shaft = profile == 'shaft'
    width = 106 if shaft else 78
    rows = []
    head = [''] * width
    head[9] = 'FRQ 1' if shaft else 'TRANSM FRQ'
    rows.extend([head, [''] * width])
    for date in ('2026-10-24', '2026-10-25'):
        for position in ((1, 2) if shaft else (3, 4)):
            for i in range(25):
                master = i == 0
                ng = master or i in (23, 24)
                row = [''] * width
                row[:8] = [date, f'09:{i:02d}:00', 'NG마스터' if master and shaft else i,
                           '사용법 예제', '합성자료', 'NG' if ng else 'OK', position, 2.5 if ng else .3]
                for slot in range(24 if shaft else 30):
                    fc = 9 + 4 * slot if shaft else 10 + 2 * slot
                    row[fc] = (slot + 1) * 100 if slot < 5 else 0
                    signal = (4 + slot * .7 if master else 2.5 if i == 24 else 0) + rng.normal(0, .3)
                    if shaft:
                        row[fc+1:fc+4] = [signal, signal * .5 + rng.normal(0, .2),
                                         100 if master and slot == 0 else abs(signal)]
                    else:
                        row[fc+1] = signal
                rows.append(row)
    def letters(index):
        text = ''
        while index:
            index, n = divmod(index - 1, 26)
            text = chr(65+n) + text
        return text
    xmlrows = []
    for rn, row in enumerate(rows, 1):
        cells = []
        for cn, value in enumerate(row, 1):
            ref = letters(cn) + str(rn)
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        xmlrows.append(f'<row r="{rn}">' + ''.join(cells) + '</row>')
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, 'w', ZIP_DEFLATED) as book:
        book.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        book.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        book.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="사용법_합성예제" sheetId="1" r:id="rId1"/></sheets></workbook>')
        book.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        book.writestr('xl/styles.xml', f'<styleSheet xmlns="{ns}"><fills count="1"><fill><patternFill patternType="none"/></fill></fills><cellXfs count="1"><xf fillId="0"/></cellXfs></styleSheet>')
        book.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{ns}"><sheetData>' + ''.join(xmlrows) + '</sheetData></worksheet>')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='사용법 확인용 합성 Excel 2개 생성')
    parser.add_argument('--output', default='data/demo/excel')
    args = parser.parse_args()
    for profile, label in [('crack', '크랙'), ('shaft', '샤프트')]:
        print(make_workbook(Path(args.output) / ('사용법_예제_' + label + '.xlsx'), profile))
