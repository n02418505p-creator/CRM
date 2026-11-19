"""PDF version of a weekly or monthly report, with the MMC Capital logo."""
import io
import logging
import urllib.request

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from xml.sax.saxutils import escape

from . import services

logger = logging.getLogger(__name__)

NAVY = colors.HexColor("#0A2A6A")
BRONZE = colors.HexColor("#C8955A")
BRONZE_DARK = colors.HexColor("#9A6B35")
INK = colors.HexColor("#16181D")
MUTED = colors.HexColor("#5B6170")
LINE = colors.HexColor("#E4DED3")
IVORY = colors.HexColor("#F7F4EE")

_logo_cache = {}


def logo_bytes():
    """The MMC Capital logo, fetched once from the website and kept in memory."""
    url = settings.BRAND_LOGO_URL
    if url not in _logo_cache:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MMC-CRM/1.0"})
            with urllib.request.urlopen(req, timeout=8) as response:
                _logo_cache[url] = response.read()
        except Exception:
            logger.warning("Could not load the logo for the PDF report from %s", url)
            return None
    return _logo_cache[url]


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Times-Roman", fontSize=22, leading=26, textColor=NAVY, alignment=0, spaceAfter=2),
        "eyebrow": ParagraphStyle("eyebrow", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=BRONZE_DARK),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Times-Roman", fontSize=14, leading=18, textColor=NAVY, spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK),
        "muted": ParagraphStyle("muted", parent=base["Normal"], fontName="Helvetica", fontSize=8, leading=10.5, textColor=MUTED),
        "kpi_value": ParagraphStyle("kpi_value", parent=base["Normal"], fontName="Times-Roman", fontSize=20, leading=22, textColor=NAVY),
        "kpi_label": ParagraphStyle("kpi_label", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=INK),
        "right": ParagraphStyle("right", parent=base["Normal"], fontName="Helvetica", fontSize=8, leading=10, textColor=MUTED, alignment=TA_RIGHT),
    }


def _p(text, style):
    return Paragraph(escape(str(text)), style)


def _table(rows, widths, header=True, zebra=True):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
        ]
    if zebra:
        for i in range(2 if header else 1, len(rows), 2):
            style.append(("BACKGROUND", (0, i), (-1, i), IVORY))
    t.setStyle(TableStyle(style))
    return t


def render(report, generated_by):
    s = _styles()
    buffer = io.BytesIO()
    width = A4[0] - 30 * mm
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
        title=f"{report['period_name']} {report['noun_plural'].lower()} report – {report['label']}", author="MMC Capital",
    )
    story = []

    # Header: logo on the left, report title on the right
    logo = logo_bytes()
    if logo:
        reader = ImageReader(io.BytesIO(logo))
        iw, ih = reader.getSize()
        logo_w = 48 * mm
        left = Image(io.BytesIO(logo), width=logo_w, height=logo_w * ih / iw)
    else:
        left = _p("MMC Capital", s["title"])
    right = [
        _p("MMC CRM · " + report["period_name"].upper() + " REPORT", s["eyebrow"]),
        _p(f"{report['noun_plural']} report", s["title"]),
        _p(f"{report['label']}  ({report['start']:%d %b %Y} – {report['end_inclusive']:%d %b %Y})", s["muted"]),
    ]
    header = Table([[left, right]], colWidths=[60 * mm, width - 60 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, BRONZE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [header, Spacer(1, 8)]

    # Headline figures
    st = report["stats"]
    change = st["change"]
    change_text = "no change on previous period" if change == 0 else (
        f"{'+' if (change or 0) > 0 else ''}{change}% on previous period ({st['previous']})" if change is not None else "none in previous period")
    kpis = [
        ("RECEIVED", st["received"], change_text),
        ("RESOLVED", st["resolved"], "in this period"),
        ("OPEN AT PERIOD END", st["open_at_end"], f"{st['overdue']} overdue (over {report['target']} days)"),
        ("AVERAGE DAYS TO RESOLVE", st["avg_days"] if st["avg_days"] is not None else "–",
         f"{st['within_pct']}% within {report['target']} days" if st["within_pct"] is not None else "nothing resolved"),
    ]
    cells = [[[_p(lbl, s["kpi_label"]), _p(val, s["kpi_value"]), _p(sub, s["muted"])] for lbl, val, sub in kpis]]
    kt = Table(cells, colWidths=[width / 4] * 4)
    kt.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), IVORY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [kt, Spacer(1, 4)]

    def breakdown(title, rows, columns=("Count", "Share")):
        data = [["", *columns]] + [[_p(r["label"], s["cell"]), r["count"], f"{r['pct']}%"] for r in rows]
        if len(data) == 1:
            data.append([_p("Nothing in this period", s["muted"]), "", ""])
        return KeepTogether([_p(title, s["h2"]), _table(data, [width * 0.62 / 2, width * 0.19 / 2, width * 0.19 / 2])])

    half = width / 2 - 4 * mm
    pair = Table([[breakdown("By status", report["by_status"]), breakdown("By source", report["by_source"])]],
                 colWidths=[half + 4 * mm, half + 4 * mm])
    pair.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(pair)

    for title, rows in report["extra"]:
        data = [["", "Count", "Share"]] + [[_p(r["label"], s["cell"]), r["count"], f"{r['pct']}%"] for r in rows]
        story.append(KeepTogether([_p(title, s["h2"]), _table(data, [width * 0.7, width * 0.15, width * 0.15])]))

    handler_rows = [["Handled by", "Received", "Resolved / closed", "Still open"]] + [
        [_p(r["label"], s["cell"]), r["received"], r["resolved"], r["open"]] for r in report["by_handler"]
    ]
    if len(handler_rows) == 1:
        handler_rows.append([_p("Nothing in this period", s["muted"]), "", "", ""])
    story.append(KeepTogether([_p("By staff member", s["h2"]), _table(handler_rows, [width * 0.46, width * 0.18, width * 0.18, width * 0.18])]))

    # Every case received in the period
    story.append(_p(f"{report['noun_plural']} received ({len(report['cases'])})", s["h2"]))
    about = "About" if report["is_enquiry"] else "Nature of the complaint"
    rows = [["Reference", "Received", "Client", about, "Handled by", "Status", "Days"]]
    for c in report["cases"]:
        detail = c.service or c.subject if report["is_enquiry"] else c.nature_of_complaint
        rows.append([
            _p(c.reference, s["cell"]),
            _p(timezone.localtime(c.date_received).strftime("%d %b %H:%M"), s["cell"]),
            _p(c.client_name + (f" ({c.organisation})" if c.organisation else ""), s["cell"]),
            _p((detail or "")[:160], s["cell"]),
            _p(services.display_name(c.assigned_to) if c.assigned_to else "Unassigned", s["cell"]),
            _p(c.get_status_display(), s["cell"]),
            c.days_open(),
        ])
    if len(rows) == 1:
        rows.append([_p("Nothing received in this period", s["muted"]), "", "", "", "", "", ""])
    story.append(_table(rows, [width * w for w in (0.17, 0.11, 0.17, 0.27, 0.13, 0.09, 0.06)]))

    generated = f"Generated {report['generated_at']:%d %b %Y %H:%M} by {services.display_name(generated_by)}"

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(15 * mm, 11 * mm, A4[0] - 15 * mm, 11 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 7 * mm, f"MMC Capital · MMC CRM · {generated} · Confidential")
        canvas.drawRightString(A4[0] - 15 * mm, 7 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
