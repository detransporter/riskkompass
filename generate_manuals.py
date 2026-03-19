#!/usr/bin/env python3
"""Genererar två manualer för Riskkompass-appen."""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, PageBreak, HRFlowable, KeepTogether,
                                 BaseDocTemplate, PageTemplate, Frame)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY

PAGE_W, PAGE_H = A4

ORANGE  = HexColor('#d4501a')
DARK    = HexColor('#1a1a1a')
MID     = HexColor('#555555')
LIGHT   = HexColor('#888888')
PALE    = HexColor('#f7f5f2')
BORDER  = HexColor('#cccccc')
TBL_HDR = HexColor('#2a2a2a')
TBL_ALT = HexColor('#f5f5f5')
RED     = HexColor('#e05252')
AMBER   = HexColor('#e0a952')
GREEN   = HexColor('#52a887')
BLUE    = HexColor('#5288e0')


def styles():
    return {
        'h1': ParagraphStyle('h1', fontName='Helvetica-Bold', fontSize=15,
                             textColor=DARK, leading=20, spaceBefore=14, spaceAfter=6),
        'h2': ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=11,
                             textColor=ORANGE, leading=16, spaceBefore=10, spaceAfter=4),
        'h3': ParagraphStyle('h3', fontName='Helvetica-Bold', fontSize=9.5,
                             textColor=DARK, leading=14, spaceBefore=6, spaceAfter=3),
        'body': ParagraphStyle('body', fontName='Helvetica', fontSize=9.5,
                               textColor=DARK, leading=14, spaceAfter=5,
                               alignment=TA_JUSTIFY),
        'small': ParagraphStyle('small', fontName='Helvetica', fontSize=8.5,
                                textColor=MID, leading=12.5, spaceAfter=3),
        'italic': ParagraphStyle('italic', fontName='Helvetica-Oblique', fontSize=8.5,
                                 textColor=LIGHT, leading=12, spaceAfter=4),
        'bullet': ParagraphStyle('bullet', fontName='Helvetica', fontSize=9.5,
                                 textColor=DARK, leading=14, leftIndent=10, spaceAfter=2),
        'mono': ParagraphStyle('mono', fontName='Courier-Bold', fontSize=9,
                               textColor=DARK, leading=13, leftIndent=8,
                               backColor=PALE, spaceAfter=4),
        'formula': ParagraphStyle('formula', fontName='Courier-Bold', fontSize=10,
                                  textColor=DARK, leading=16, leftIndent=16, spaceAfter=4),
        'label': ParagraphStyle('label', fontName='Helvetica-Bold', fontSize=7.5,
                                textColor=LIGHT, leading=11, spaceAfter=2),
        'center': ParagraphStyle('center', fontName='Helvetica', fontSize=8,
                                 textColor=LIGHT, leading=11, alignment=TA_CENTER),
    }


def tbl_style(header=True):
    s = [
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 8.5),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [white, TBL_ALT]),
        ('GRID', (0,0), (-1,-1), 0.4, BORDER),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]
    if header:
        s += [
            ('BACKGROUND', (0,0), (-1,0), TBL_HDR),
            ('TEXTCOLOR', (0,0), (-1,0), white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 8.5),
        ]
    return TableStyle(s)


def info_box(text, S, accent=ORANGE):
    t = Table([[Paragraph(text, S['small'])]], colWidths=[PAGE_W - 40*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), PALE),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER),
        ('LINEBEFORE', (0,0), (0,-1), 3, accent),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    return t


# ══════════════════════════════════════════════════════════════════════════════
# FULLSTÄNDIG MANUAL
# ══════════════════════════════════════════════════════════════════════════════

def build_full_manual(path):
    S = styles()
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=22*mm, rightMargin=22*mm,
                            topMargin=26*mm, bottomMargin=28*mm)

    def on_cover(canvas, doc):
        canvas.setFillColor(DARK)
        canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        canvas.setFillColor(ORANGE)
        canvas.rect(0, PAGE_H - 10*mm, PAGE_W, 10*mm, fill=1, stroke=0)
        canvas.rect(0, 0, 5*mm, PAGE_H, fill=1, stroke=0)
        canvas.setFillColor(HexColor('#111'))
        canvas.rect(0, 0, PAGE_W, 28*mm, fill=1, stroke=0)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(LIGHT)
        canvas.drawString(22*mm, 10*mm, 'SCM International · David Leifsson · 2026')

    def on_page(canvas, doc):
        canvas.setFillColor(ORANGE)
        canvas.rect(0, PAGE_H - 3*mm, PAGE_W, 3*mm, fill=1, stroke=0)
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(22*mm, 20*mm, PAGE_W - 22*mm, 20*mm)
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(LIGHT)
        canvas.drawString(22*mm, 14*mm, 'SCM International · Riskkompass · Fullständig Manual')
        canvas.drawRightString(PAGE_W - 22*mm, 14*mm, f'Sida {doc.page}')

    story = []

    # ── OMSLAG ────────────────────────────────────────────────────────────────
    cover_ps = lambda sz, bold=False, col=white: ParagraphStyle(
        'cp', fontName='Helvetica-Bold' if bold else 'Helvetica',
        fontSize=sz, textColor=col, leading=sz*1.3)

    story += [
        Spacer(1, 40*mm),
        Paragraph('Supply Chain', cover_ps(13, col=HexColor('#aaa'))),
        Paragraph('Riskkompass', cover_ps(34, bold=True)),
        Spacer(1, 3*mm),
        Paragraph('Hormuz/Röda havet · Scenario 2026', cover_ps(13, col=ORANGE)),
        Spacer(1, 8*mm),
        HRFlowable(width='100%', thickness=0.5, color=HexColor('#333')),
        Spacer(1, 6*mm),
        Paragraph('Fullständig Användarmanual', cover_ps(12, bold=True, col=HexColor('#ccc'))),
        Paragraph('Version 1.0 · Mars 2026', cover_ps(9, col=HexColor('#666'))),
        Spacer(1, 55*mm),
        Paragraph('SCM International', cover_ps(11, bold=True)),
        Paragraph('David Leifsson · Supply Chain & Logistics Consultant',
                  cover_ps(9, col=HexColor('#888'))),
        PageBreak(),
    ]

    # ── INNEHÅLLSFÖRTECKNING ──────────────────────────────────────────────────
    story.append(Paragraph('Innehållsförteckning', S['h1']))
    story.append(HRFlowable(width='100%', thickness=1, color=ORANGE, spaceAfter=8))

    toc = [
        ('1.', 'Introduktion', False),
        ('2.', 'Komma igång — Starta appen', False),
        ('3.', 'Datakrav och filformat', False),
        ('  3.1', 'Obligatoriska kolumner', True),
        ('  3.2', 'Exempelmall och filformat', True),
        ('4.', 'Scenarioval', False),
        ('5.', 'Parametrar', False),
        ('  5.1', 'Servicenivå och z-värde', True),
        ('  5.2', 'Dött lager och slow movers', True),
        ('6.', 'Datainmatning', False),
        ('  6.1', 'Filuppladdning', True),
        ('  6.2', 'Manuell inmatning', True),
        ('7.', 'Analysresultat', False),
        ('  7.1', 'KPI-sammanfattning', True),
        ('  7.2', 'Riskfördelning', True),
        ('  7.3', 'Artiklar i stockout-risk', True),
        ('  7.4', 'Överlager och dött lager', True),
        ('  7.5', 'Säkerhetslagernivåer', True),
        ('  7.6', 'ABC-avvikelser', True),
        ('8.', 'Beräkningsmetodik', False),
        ('  8.1', 'Säkerhetslager (SS)', True),
        ('  8.2', 'Ombeställningspunkt (ROP)', True),
        ('  8.3', 'Lagertäckningsgrad (DOS)', True),
        ('  8.4', 'ABC-klassificering', True),
        ('  8.5', 'Stockout-riskbedömning', True),
        ('  8.6', 'Akut inköpsbehov', True),
        ('9.', 'Export och rapportering', False),
        ('10.', 'Begränsningar och antaganden', False),
    ]
    for num, title, sub in toc:
        ps = ParagraphStyle('toc_sub' if sub else 'toc',
                            fontName='Helvetica', fontSize=9.5 if not sub else 9,
                            textColor=MID if sub else DARK, leading=15,
                            leftIndent=16 if sub else 0)
        story.append(Paragraph(f'<b>{num}</b>  {title}', ps))
    story.append(PageBreak())

    # ── SEKTION 1 ─────────────────────────────────────────────────────────────
    story.append(Paragraph('1. Introduktion', S['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5))
    story.append(Paragraph(
        'Riskkompass är ett beslutsstödverktyg byggt i Python/Streamlit '
        'för att kvantifiera hur ett företags lagerposition påverkas av störningar i de globala '
        'sjöfartsrutterna — specifikt Hormuzstredet och Röda havet.',
        S['body']))
    story.append(Paragraph(
        'Appen riktar sig till supply chain-ansvariga, inköpschefer och logistikledning som '
        'behöver snabbt svara på frågorna: <i>"Hur länge räcker vårt lager om ledtiderna '
        'fördubblas?"</i> och <i>"Vad behöver vi köpa in nu?"</i>',
        S['body']))
    story.append(Paragraph('Vad appen gör:', S['h2']))
    for b in [
        'Simulerar tre geopolitiska scenarier med ökade ledtider (×1.4 / ×1.8 / ×2.5)',
        'Beräknar nytt säkerhetslager och ombeställningspunkt per artikel',
        'Identifierar artiklar vars saldo redan understiger den nya ombeställningspunkten',
        'Kvantifierar det akuta inköpsbehovet i SEK',
        'Klassar artiklar i KRITISK / HÖG / MEDEL / LÅG-risk',
        'Analyserar ABC-klassificering baserad på faktisk årsförbrukning (ej lagervärde)',
        'Flaggar dött lager och slow movers som binder kapital onödigt',
        'Exporterar fullständig rapport till Excel med fyra flikar',
    ]:
        story.append(Paragraph(f'• {b}', S['bullet']))
    story.append(Spacer(1, 4*mm))
    story.append(info_box(
        '<b>Användningskontext:</b> Verktyget är designat för SME-företag med manuella '
        'lagerfiler i Excel eller ERP-exporter (t.ex. Visma, Monitor, Pyramid). '
        'Inga molntjänster eller externa API:er används — all analys sker lokalt.', S))
    story.append(Spacer(1, 4*mm))

    # ── SEKTION 2 ─────────────────────────────────────────────────────────────
    story.append(Paragraph('2. Komma igång — Starta appen', S['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5))
    story.append(Paragraph('Förutsättningar — installera beroenden:', S['h2']))
    story.append(Paragraph('pip install streamlit pandas numpy openpyxl', S['mono']))
    story.append(Paragraph('Starta appen:', S['h3']))
    story.append(Paragraph('streamlit run scm-expoure-war.py', S['mono']))
    story.append(Paragraph(
        'Appen öppnas automatiskt i din standardwebbläsare på <b>http://localhost:8501</b>. '
        'Håll terminalfönstret öppet under hela sessionen — stängs terminalen stängs appen.',
        S['body']))
    story.append(Spacer(1, 4*mm))

    # ── SEKTION 3 ─────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph('3. Datakrav och filformat', S['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5))
    story.append(Paragraph('3.1 Obligatoriska kolumner', S['h2']))
    story.append(Paragraph(
        'Filen måste innehålla exakt dessa nio kolumner. Kolumnnamnen är '
        'skiftlägeskänsliga (lowercase).', S['body']))

    col_data = [
        ['Kolumn', 'Datatyp', 'Beskrivning', 'Exempel'],
        ['artikel_nr', 'Text', 'Unikt artikelnummer', 'ART-001'],
        ['beskrivning', 'Text', 'Artikelbeskrivning', 'Hydraulpump A'],
        ['abc_klass', 'A/B/C', 'Manuellt satt ABC-klass', 'A'],
        ['lead_time_dagar', 'Heltal', 'Normal ledtid i dagar', '45'],
        ['efterfragan_snitt_dag', 'Decimal', 'Genomsnittlig daglig efterfrågan (enheter)', '2.5'],
        ['efterfragan_std_dag', 'Decimal', 'Standardavvikelse för daglig efterfrågan', '0.8'],
        ['lager_saldo', 'Heltal', 'Nuvarande lagersaldo (enheter)', '80'],
        ['enhetspris_sek', 'Heltal', 'Pris per enhet (SEK)', '4 500'],
        ['dagar_utan_rorelse', 'Heltal', 'Dagar sedan senaste lagerrörelse', '12'],
    ]
    col_rows = [[Paragraph(c, ParagraphStyle('cc', fontName='Courier' if i > 0 and j == 0
                           else 'Helvetica-Bold' if i == 0 else 'Helvetica',
                           fontSize=8.5, textColor=white if i == 0 else DARK, leading=12))
                 for j, c in enumerate(row)] for i, row in enumerate(col_data)]
    ct = Table(col_rows, colWidths=[38*mm, 20*mm, 72*mm, 26*mm])
    ct.setStyle(tbl_style())
    story.append(ct)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph('3.2 Exempelmall och filformat', S['h2']))
    story.append(Paragraph(
        'En färdig Excel-mall laddas ned direkt i appen under fliken <b>Ladda upp CSV/Excel</b> '
        '→ knappen <b>"⬇ Ladda ned Excel-mall"</b>. Filen innehåller fem exempelartiklar med '
        'alla korrekta kolumnnamn och exempelvärden.', S['body']))
    story.append(Paragraph(
        'Appen stödjer även <b>CSV-filer</b> och detekterar automatiskt om filen är i '
        '<b>svenskt format</b> (semikolon som kolumnseparator, komma som decimaltecken) '
        '— vilket är standard för Excel-exporter på svenska datorer. Ingen manuell '
        'inställning krävs.', S['body']))
    story.append(info_box(
        '<b>Kolumnvalidering:</b> Om en uppladdad fil saknar en eller flera obligatoriska '
        'kolumner visas ett felmeddelande med en exakt lista över saknade kolumner. '
        'Appen kraschar inte — du kan korrigera filen och ladda upp igen.', S))
    story.append(Spacer(1, 4*mm))

    # ── SEKTION 4 ─────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph('4. Scenarioval', S['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5))
    story.append(Paragraph(
        'Scenariot väljs i den vänstra sidopanelen och styr hur mycket alla ledtider '
        'multipliceras. Alla beräkningar (SS, ROP, stockout-risk) uppdateras i realtid '
        'när scenariot ändras.', S['body']))

    sc_data = [
        ['Scenario', 'Multiplikator', 'Geopolitisk tolkning'],
        ['Basfall — Vapenvila inom 2 mån', '×1.40 (+40%)',
         'Konflikten avtar relativt snabbt. Viss omdirigering via Kap Horn '
         'ger måttligt ökade ledtider. Lämpligt som planeringsbasfall.'],
        ['Förlängt krig — Hormuz stängt', '×1.80 (+80%)',
         'Hormuzstredet hålls stängt >6 månader. Alla fartyg från/till '
         'Persiska viken tvingas runt Afrika (+10–14 dagars segling). '
         'Hög press på sjöfart och hamnkapacitet.'],
        ['Worst case — Hormuz + Röda havet', '×2.50 (+150%)',
         'Dubbelstrypning: Hormuz blockerat + Houthi-attacker i Röda havet '
         'tvingar om Suezkanalen. Maximalt tryck. Kombinerade störningar '
         'kan ge ledtider 2–3× normalt.'],
    ]
    sc_rows = []
    for i, row in enumerate(sc_data):
        colors_row = [white if i == 0 else DARK] * 3
        fonts = ['Helvetica-Bold'] * 3 if i == 0 else ['Helvetica'] * 3
        mc = [GREEN, AMBER, RED][i-1] if i > 0 else white
        r = [Paragraph(c, ParagraphStyle('sc', fontName=fonts[j], fontSize=8.5,
                        textColor=(mc if j == 1 and i > 0 else (white if i == 0 else DARK)),
                        leading=13)) for j, c in enumerate(row)]
        sc_rows.append(r)
    sc_t = Table(sc_rows, colWidths=[52*mm, 26*mm, 88*mm])
    sc_t.setStyle(tbl_style())
    story.append(sc_t)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        'Tre indikatorkort visas högst upp på sidan med aktivt scenario, '
        'procentuell ledtidsökning och servicenivå — färgkodade grönt/gult/rött.',
        S['body']))
    story.append(Spacer(1, 4*mm))

    # ── SEKTION 5 ─────────────────────────────────────────────────────────────
    story.append(Paragraph('5. Parametrar', S['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5))

    story.append(Paragraph('5.1 Servicenivå och z-värde', S['h2']))
    story.append(Paragraph(
        'Servicenivån (reglage 90–99%, standard 95%) bestämmer hur konservativt '
        'säkerhetslagret dimensioneras. En högre servicenivå ger ett större '
        'säkerhetslager och minskar risken för stockout — men ökar kapitalbindningen.',
        S['body']))

    sl_data = [
        ['Servicenivå', '90%', '91%', '92%', '93%', '94%', '95%', '96%', '97%', '98%', '99%'],
        ['z-värde',     '1.28','1.34','1.41','1.48','1.56','1.65','1.75','1.88','2.05','2.33'],
    ]
    sl_t = Table(sl_data, colWidths=[28*mm] + [14.4*mm]*10)
    sl_t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), TBL_HDR),
        ('TEXTCOLOR', (0,0), (-1,0), white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTNAME', (0,0), (0,0), 'Helvetica-Bold'),
        ('FONTNAME', (0,1), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,1), (-1,-1), 'Courier'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [TBL_ALT]),
        ('GRID', (0,0), (-1,-1), 0.4, BORDER),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('ALIGN', (1,0), (-1,-1), 'CENTER'),
        ('BACKGROUND', (6,0), (6,0), ORANGE),
        ('BACKGROUND', (6,1), (6,-1), HexColor('#fff0eb')),
    ]))
    story.append(sl_t)
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        '<i>Rekommendation: 95% för A-artiklar (kritiska), 90% för C-artiklar. '
        'Appen applicerar ett enhetligt z-värde på hela datasetet.</i>', S['italic']))

    story.append(Paragraph('5.2 Dött lager och slow movers', S['h2']))
    story.append(Paragraph(
        'Två rörlighetsgränser konfigureras i sidopanelen:', S['body']))
    story.append(Paragraph(
        '• <b>Dött lager</b> (standard 120 dagar): Artiklar vars <i>dagar_utan_rorelse</i> '
        'överstiger gränsen. Dessa artiklar genererar ingen omsättning och binder kapital. '
        'Under en supply chain-störning är detta kapital som kan frigöras och omplaceras '
        'till akuta inköp.', S['bullet']))
    story.append(Paragraph(
        '• <b>Slow mover</b> (standard 60 dagar): Artiklar med rörelse som är trög — '
        'över slow mover-gränsen men under dött lager-gränsen. Bevakningskategori.',
        S['bullet']))
    story.append(Spacer(1, 4*mm))

    # ── SEKTION 6 ─────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph('6. Datainmatning', S['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5))

    story.append(Paragraph('6.1 Filuppladdning', S['h2']))
    story.append(Paragraph(
        'Fliken <b>Ladda upp CSV/Excel</b> är primärt inmatningssätt för produktionsdrift. '
        'Appen accepterar <b>.xlsx</b> och <b>.csv</b>. Analysen startar automatiskt '
        'direkt när en giltig fil laddas upp.', S['body']))
    for s in [
        '1. Klicka <b>"Browse files"</b> eller dra och släpp filen i uppladdningsfältet.',
        '2. Appen validerar att alla nio obligatoriska kolumner finns.',
        '3. Vid saknade kolumner: felmeddelande med lista. Rätta filen och ladda upp igen.',
        '4. Vid godkänd fil: <b>"✓ N artiklar inlästa"</b> — analysen renderas omedelbart.',
    ]:
        story.append(Paragraph(s, S['bullet']))
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph('6.2 Manuell inmatning', S['h2']))
    story.append(Paragraph(
        'Fliken <b>Manuell inmatning</b> lämpar sig för snabba scenariokörningar med '
        'ett fåtal artiklar (max 20) utan att förbereda en fil. Fem exempelartiklar är '
        'förifyllda med realistiska värden. Justera värdena och klicka '
        '<b>"Kör analys →"</b>.', S['body']))
    story.append(Spacer(1, 4*mm))

    # ── SEKTION 7 ─────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph('7. Analysresultat', S['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5))

    story.append(Paragraph('7.1 KPI-sammanfattning', S['h2']))
    story.append(Paragraph(
        'Fem nyckeltal visas i rad direkt under scenarioindikatorn. '
        'De uppdateras omedelbart vid scenariobyte eller parameterändring.', S['body']))
    kpi_data = [
        ['KPI', 'Beräkning', 'Tolkning'],
        ['Artiklar i stockout-risk', 'Saldo < ROP_nytt', 'Antal artiklar vars nuvarande saldo '
         'understiger ombeställningspunkten i valt scenario. Dessa kräver åtgärd.'],
        ['Dött/slow-mover lager', 'Dagar utan rörelse ≥ tröskel',
         'Antal artiklar klassade som slow mover eller dött lager.'],
        ['Kapital i dött lager', 'Saldo × pris (döda artiklar)',
         'Total SEK bunden i artiklar utan rörelse. Kan frigöras.'],
        ['Extra SS-kapital', 'SS_delta × enhetspris',
         'Ytterligare kapital som krävs för att höja säkerhetslagret till rätt nivå.'],
        ['Akut inköpsbehov', 'max(0, ROP_ny − saldo) × pris',
         'Totalt inköpsvärde (SEK) som behöver läggas omgående för att täcka alla stockout-risker.'],
    ]
    kpi_rows = [[Paragraph(c, ParagraphStyle('kc', fontName='Helvetica-Bold' if i == 0
                            else 'Helvetica', fontSize=8.5, textColor=white if i == 0 else DARK,
                            leading=13)) for c in row] for i, row in enumerate(kpi_data)]
    kt = Table(kpi_rows, colWidths=[38*mm, 46*mm, 82*mm])
    kt.setStyle(tbl_style())
    story.append(kt)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph('7.2 Riskfördelning', S['h2']))
    story.append(Paragraph(
        'Fyra färgkodade kort visar antal artiklar per risknivå med procentandel. '
        'Ger en omedelbar överblick utan att behöva läsa detaljerade tabeller. '
        'Färgerna följer appens riskkodning: rött = KRITISK, gult = HÖG, '
        'ljusgult = MEDEL, grönt = LÅG.', S['body']))

    risk_data = [
        ['Risknivå', 'Kriterium', 'Rekommenderad åtgärd'],
        ['KRITISK', 'Saldo < ROP_ny OCH ABC-klass A',
         'Akut inköp. Kontakta leverantör direkt. Bygg buffertlager omedelbart.'],
        ['HÖG', 'Saldo < ROP_ny OCH ABC-klass B eller C',
         'Prioriterat inköp inom 1–2 veckor.'],
        ['MEDEL', 'DOS < LT_ny × 1.5 (ej i stockout)',
         'Planera inköp. Bevaka noga.'],
        ['LÅG', 'DOS ≥ LT_ny × 1.5',
         'Ingen omedelbar åtgärd krävs.'],
    ]
    risk_rows = []
    risk_colors = [white, RED, AMBER, HexColor('#e0c852'), GREEN]
    for i, row in enumerate(risk_data):
        r = [Paragraph(c, ParagraphStyle('rc', fontName='Helvetica-Bold' if i == 0 or j == 0
                        else 'Helvetica', fontSize=8.5,
                        textColor=white if i == 0 else (risk_colors[i] if j == 0 else DARK),
                        leading=13)) for j, c in enumerate(row)]
        risk_rows.append(r)
    rt = Table(risk_rows, colWidths=[22*mm, 56*mm, 88*mm])
    rt.setStyle(tbl_style())
    story.append(rt)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph('7.3 Artiklar i stockout-risk', S['h2']))
    story.append(Paragraph(
        'Tabell med alla artiklar vars lagersaldo understiger ROP för det valda scenariot. '
        'Sorteras efter risknivå (KRITISK överst).', S['body']))
    story.append(Paragraph('Kolumner i tabellen:', S['h3']))
    for name, desc in [
        ('Artikel / Beskrivning / ABC / Risk', 'Identifierande information och risknivå'),
        ('DOS (dagar)', 'Nuvarande lagertäckning: saldo ÷ genomsnittlig daglig efterfrågan'),
        ('LT original / LT nytt', 'Ledtid i normalt läge och under valt scenario (dagar)'),
        ('Saldo', 'Nuvarande lagerkvantitet (enheter)'),
        ('ROP nytt', 'Ombeställningspunkten beräknad för scenariot'),
        ('Inköp (antal)', 'max(0, ROP_ny − saldo) — enheter som behöver köpas in'),
        ('Akut inköp (SEK)', 'Inköpsantal × enhetspris — inköpsbelopp i SEK per artikel'),
    ]:
        story.append(Paragraph(f'• <b>{name}:</b> {desc}', S['bullet']))
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph('7.4 Överlager och dött lager', S['h2']))
    story.append(Paragraph(
        'Artiklar klassade som dött lager eller slow mover listas med status, dagar utan '
        'rörelse och bundet kapital. En summering visar totalt bundet kapital.', S['body']))
    story.append(Paragraph(
        'Under en supply chain-störning är det strategiskt viktigt att identifiera detta '
        'kapital — det kan frigöras via avveckling eller kampanjer och omplaceras till '
        'akuta inköp av riskartiklar.', S['body']))
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph('7.5 Säkerhetslagernivåer', S['h2']))
    story.append(Paragraph(
        'Artikel-för-artikel-vy av säkerhetslagrets förändring: ursprungsnivå, ny nivå '
        'under scenariot, delta (förändring i enheter) och extra kapitalbindning (SEK). '
        'ROP-original och ROP-nytt visas för direkt jämförelse.', S['body']))
    story.append(Paragraph(
        'Tabellen är utformad för att skickas direkt till inköpsavdelningen som '
        'beslutsunderlag.', S['body']))
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph('7.6 ABC-avvikelser', S['h2']))
    story.append(Paragraph(
        'Visas enbart om systemets beräknade ABC-klass skiljer sig från den manuellt '
        'angivna klassen i datafilen. Systemet klassar baserat på årsförbrukningsvärde '
        '(efterfrågan/dag × 365 × pris). Avvikelser indikerar ofta föråldrade manuella '
        'klassificeringar.', S['body']))
    story.append(info_box(
        '<b>Viktig distinktion:</b> Att klassificera ABC på <i>lagervärde</i> (vanligt '
        'fel i Excel-modeller) ger missvisande resultat — en artikel med mycket i lager '
        'men låg omsättning hamnar i A, medan en snabbrörlig billigartikel klassas C. '
        'Appen använder årsförbrukningsvärde i enlighet med Pareto-principen.', S, AMBER))
    story.append(Spacer(1, 4*mm))

    # ── SEKTION 8 ─────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph('8. Beräkningsmetodik', S['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5))

    story.append(Paragraph('8.1 Säkerhetslager (SS)', S['h2']))
    story.append(Paragraph(
        'Säkerhetslagret beräknas med klassisk normalfördelningsbaserad formel som tar '
        'hänsyn till efterfrågevariabilitet och ledtidens längd:', S['body']))
    story.append(Paragraph('SS = z × σ_d × √LT', S['formula']))
    for label, desc in [
        ('z', 'Z-värde för vald servicenivå (t.ex. 1.65 för 95%)'),
        ('σ_d', 'Standardavvikelse för daglig efterfrågan (kolumn: efterfragan_std_dag)'),
        ('LT', 'Ledtid i dagar — beräknas för original-LT och scenario-justerad LT'),
    ]:
        story.append(Paragraph(f'• <b>{label}</b> = {desc}', S['bullet']))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        '<i>Notering: Formeln förutsätter konstant ledtid och normalfördelad efterfrågan. '
        'En mer fullständig formel som inkluderar LT-variabilitet är: '
        'SS = z × √(LT × σ_d² + μ_d² × σ_LT²) — men kräver data om LT-standardavvikelse '
        'som sällan finns tillgänglig. Modellen är konservativ i ett störningsscenario.</i>',
        S['italic']))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph('8.2 Ombeställningspunkt (ROP)', S['h2']))
    story.append(Paragraph(
        'ROP anger det lagersaldo vid vilket en ny order ska läggas, så att '
        'säkerhetslagret inte understiger noll under leveransväntetiden:', S['body']))
    story.append(Paragraph('ROP = μ_d × LT + SS', S['formula']))
    for label, desc in [
        ('μ_d', 'Genomsnittlig daglig efterfrågan (kolumn: efterfragan_snitt_dag)'),
        ('LT', 'Ledtid i dagar'),
        ('SS', 'Beräknat säkerhetslager (se 8.1)'),
    ]:
        story.append(Paragraph(f'• <b>{label}</b> = {desc}', S['bullet']))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph('8.3 Lagertäckningsgrad — DOS (Days of Stock)', S['h2']))
    story.append(Paragraph('DOS = Lager_saldo ÷ Efterfrågan_snitt_dag', S['formula']))
    story.append(Paragraph(
        'DOS anger hur många dagar det nuvarande lagret räcker vid genomsnittlig '
        'efterfrågan. Artiklar med noll efterfrågan tilldelas DOS = 999 (formelskydd).',
        S['body']))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph('8.4 ABC-klassificering', S['h2']))
    story.append(Paragraph(
        'ABC beräknas på årsförbrukningsvärde per artikel — ej lagervärde:', S['body']))
    story.append(Paragraph(
        'Årsförbrukningsvärde = Efterfrågan_snitt_dag × 365 × Enhetspris', S['formula']))
    story.append(Paragraph('Pareto-klassificering:', S['h3']))
    for klass, span in [('A-artiklar', 'Topp 80% av total årsförbrukning'),
                         ('B-artiklar', 'Nästa 15% (kumulativt 80–95%)'),
                         ('C-artiklar', 'Sista 5% (kumulativt 95–100%)')]:
        story.append(Paragraph(f'• <b>{klass}:</b> {span}', S['bullet']))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph('8.5 Stockout-riskbedömning', S['h2']))
    story.append(Paragraph(
        'En artikel är i stockout-risk om nuvarande saldo understiger '
        'ombeställningspunkten för det valda scenariot:', S['body']))
    story.append(Paragraph('Stockout_risk = (Lager_saldo < ROP_nytt)', S['formula']))
    story.append(Paragraph(
        'Risknivån sätts sedan baserat på kombination av stockout-risk och ABC-klass: '
        'KRITISK = stockout-risk + A-klass, HÖG = stockout-risk + B/C-klass, '
        'MEDEL = DOS < LT_ny × 1.5 (ej stockout), LÅG = övriga.', S['body']))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph('8.6 Akut inköpsbehov', S['h2']))
    story.append(Paragraph('Beräknas per artikel:', S['body']))
    story.append(Paragraph('Inköp_antal = max(0, ROP_nytt − Lager_saldo)', S['formula']))
    story.append(Paragraph('Inköp_SEK = Inköp_antal × Enhetspris', S['formula']))
    story.append(Paragraph(
        'Summan av Inköp_SEK för alla artiklar utgör KPI:n "Akut inköpsbehov" — '
        'det minimala inköpsbelopp som krävs för att täcka samtliga stockout-risker '
        'under det valda scenariot.', S['body']))

    # ── SEKTION 9 ─────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph('9. Export och rapportering', S['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5))
    story.append(Paragraph(
        'Klicka <b>"⬇ Ladda ned analysrapport (Excel)"</b> längst ned på sidan. '
        'Filnamnet inkluderar det aktiva scenariot automatiskt.', S['body']))
    exp_data = [
        ['Excel-flik', 'Innehåll'],
        ['Rådata + beräkningar',
         'All data inklusive samtliga beräknade kolumner (SS, ROP, DOS, inköpsbehov m.m.)'],
        ['Stockout-risk',
         'Filtrad vy: enbart artiklar i stockout-risk (flik utelämnas om inga finns)'],
        ['Dött lager',
         'Filtrad vy: slow movers och dött lager (flik utelämnas om inga finns)'],
        ['Säkerhetslagernivåer',
         'Renformaterad SS/ROP-tabell utformad för distribution till inköpsavdelning'],
    ]
    exp_rows = [[Paragraph(c, ParagraphStyle('ec', fontName='Helvetica-Bold' if i == 0
                            else ('Courier' if j == 0 else 'Helvetica'),
                            fontSize=8.5, textColor=white if i == 0 else DARK, leading=13))
                 for j, c in enumerate(row)] for i, row in enumerate(exp_data)]
    et = Table(exp_rows, colWidths=[46*mm, 120*mm])
    et.setStyle(tbl_style())
    story.append(et)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        'Exportfilen kan skickas direkt till inköpsavdelning, ekonomiavdelning eller '
        'ledning utan ytterligare bearbetning.', S['body']))

    # ── SEKTION 10 ────────────────────────────────────────────────────────────
    story.append(Paragraph('10. Begränsningar och antaganden', S['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5))
    for title, text in [
        ('Normalfördelad efterfrågan',
         'Modellen förutsätter att daglig efterfrågan är normalfördelad. Starkt '
         'säsongsbetonade produkter eller artiklar med få stora ordrar kan ge '
         'missvisande SS-beräkningar.'),
        ('Konstant ledtid i formeln',
         'SS-formeln tar inte hänsyn till LT-variabilitet. Under ett Hormuz-scenario '
         'är LT-variabiliteten hög i verkligheten — SS kan behöva vara större.'),
        ('Inga transportkostnader',
         'Analysen hanterar enbart inköpsvärde. Extrakostnader för omdirigering '
         'via Kap Horn, flygfrakt eller premiumleverantörer är inte inkluderade.'),
        ('Statisk efterfrågan',
         'Appen förutsätter konstant daglig efterfrågan. Störningar påverkar '
         'ofta även efterfrågan — detta modelleras inte.'),
        ('En multiplikator per scenario',
         'Alla artiklar påverkas med samma LT-multiplikator. I verkligheten varierar '
         'exponeringen beroende på ursprungsland och leverantörens logistikupplägg.'),
        ('ABC baseras på daglig snittefterfrågan',
         'Om data avser enstaka månader snarare än ett normalår kan '
         'ABC-klassificeringen bli missvisande.'),
    ]:
        story.append(KeepTogether([
            Paragraph(f'• <b>{title}:</b>', S['bullet']),
            Paragraph(f'  {text}', S['small']),
            Spacer(1, 3*mm),
        ]))

    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        'SCM International · David Leifsson · Riskkompass · '
        'Version 1.0 · Mars 2026', S['center']))

    doc.build(story, onFirstPage=on_cover, onLaterPages=on_page)
    print(f'✓  Manual: {path}')


# ══════════════════════════════════════════════════════════════════════════════
# QUICK START ONE-PAGER
# ══════════════════════════════════════════════════════════════════════════════

def build_quickstart(path):
    S = styles()

    doc = BaseDocTemplate(path, pagesize=A4,
                          leftMargin=16*mm, rightMargin=16*mm,
                          topMargin=18*mm, bottomMargin=18*mm)

    def qs_bg(canvas, doc):
        canvas.setFillColor(ORANGE)
        canvas.rect(0, PAGE_H - 13*mm, PAGE_W, 13*mm, fill=1, stroke=0)
        canvas.rect(0, 0, 4*mm, PAGE_H - 13*mm, fill=1, stroke=0)
        canvas.setFillColor(DARK)
        canvas.rect(4*mm, 0, PAGE_W - 4*mm, 14*mm, fill=1, stroke=0)
        # Header text
        canvas.setFont('Helvetica-Bold', 16)
        canvas.setFillColor(white)
        canvas.drawString(17*mm, PAGE_H - 9*mm, 'QUICK START')
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(HexColor('#ffe0d0'))
        canvas.drawString(17*mm + 76*mm, PAGE_H - 9*mm,
                          'Riskkompass · SCM International')
        # Footer
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(LIGHT)
        canvas.drawString(17*mm, 5.5*mm,
                          'SCM International · David Leifsson · Riskkompass · Version 1.0 · Mars 2026')

    frame = Frame(16*mm, 14*mm, PAGE_W - 20*mm, PAGE_H - 32*mm, id='main')
    doc.addPageTemplates([PageTemplate(id='qs', frames=[frame], onPage=qs_bg)])

    b  = ParagraphStyle('b',  fontName='Helvetica',      fontSize=8.5, textColor=DARK,  leading=12.5, spaceAfter=2)
    bh = ParagraphStyle('bh', fontName='Helvetica-Bold', fontSize=8.5, textColor=DARK,  leading=12.5, spaceAfter=2)
    lbl= ParagraphStyle('lbl',fontName='Helvetica-Bold', fontSize=7.5, textColor=LIGHT, leading=11,   spaceAfter=2)
    mo = ParagraphStyle('mo', fontName='Courier-Bold',   fontSize=8.5, textColor=DARK,  leading=13,   backColor=PALE, spaceAfter=3)
    bl = ParagraphStyle('bl', fontName='Helvetica',      fontSize=8,   textColor=DARK,  leading=12,   leftIndent=7,   spaceAfter=1)
    sml= ParagraphStyle('sml',fontName='Helvetica',      fontSize=7.5, textColor=MID,   leading=11,   spaceAfter=2)

    story = [Spacer(1, 13*mm)]

    # ── Intro ─────────────────────────────────────────────────────────────────
    intro_t = Table([[Paragraph(
        '<b>Appen simulerar hur störningar i Hormuzstredet och Röda havet påverkar ditt lager.</b> '
        'Mata in artikeldata → välj scenario → se vilka artiklar som är i stockout-risk '
        'och exakt hur mycket du behöver köpa in nu.', b)
    ]], colWidths=[PAGE_W - 36*mm])
    intro_t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), PALE),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER),
        ('LINEBEFORE', (0,0), (0,-1), 3, ORANGE),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story += [intro_t, Spacer(1, 4*mm)]

    # ── Två kolumner: Starta + Scenarion | Datakrav ───────────────────────────
    left = [
        Paragraph('STARTA APPEN', lbl),
        Paragraph('streamlit run scm-expoure-war.py', mo),
        Paragraph('Öppnas på <b>http://localhost:8501</b>', b),
        Spacer(1, 4*mm),
        Paragraph('VÄLJ SCENARIO (sidopanel)', lbl),
    ]
    for mult, pct, name, col in [
        ('×1.40', '+40%', 'Vapenvila 2 mån',        '#52a887'),
        ('×1.80', '+80%', 'Hormuz stängt',           '#e0a952'),
        ('×2.50', '+150%','Hormuz + Röda havet',     '#e05252'),
    ]:
        row_t = Table([[
            Paragraph(f'<b>{mult}</b>', ParagraphStyle('sm', fontName='Helvetica-Bold',
                       fontSize=9, textColor=HexColor(col), leading=12)),
            Paragraph(f'<font color="#999">{pct}</font>  {name}', b),
        ]], colWidths=[11*mm, 63*mm])
        row_t.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 1),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ]))
        left.append(row_t)
    left += [
        Spacer(1, 4*mm),
        Paragraph('PARAMETRAR (sidopanel)', lbl),
        Paragraph('• Servicenivå: 90–99% (standard 95%)', bl),
        Paragraph('• Dött lager: std 120 dagar utan rörelse', bl),
        Paragraph('• Slow mover: std 60 dagar utan rörelse', bl),
    ]

    right = [Paragraph('DATAKRAV — 9 KOLUMNER (.xlsx / .csv)', lbl)]
    col_mini = [
        ('artikel_nr',          'ART-001'),
        ('beskrivning',         'Hydraulpump A'),
        ('abc_klass',           'A / B / C'),
        ('lead_time_dagar',     '45'),
        ('efterfragan_snitt_dag','2.5'),
        ('efterfragan_std_dag', '0.8'),
        ('lager_saldo',         '80'),
        ('enhetspris_sek',      '4500'),
        ('dagar_utan_rorelse',  '12'),
    ]
    cm_data = [['Kolumn', 'Ex.']] + list(col_mini)
    cm_t = Table(cm_data, colWidths=[50*mm, 22*mm])
    cm_t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), TBL_HDR),
        ('TEXTCOLOR', (0,0), (-1,0), white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 7.5),
        ('FONTNAME', (0,1), (0,-1), 'Courier'),
        ('FONTNAME', (1,1), (1,-1), 'Helvetica'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [white, TBL_ALT]),
        ('GRID', (0,0), (-1,-1), 0.3, BORDER),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    right.append(cm_t)
    right += [
        Spacer(1, 2*mm),
        Paragraph('⬇ Ladda ned mall direkt i appen',
                  ParagraphStyle('dl', fontName='Helvetica-Oblique', fontSize=7.5,
                                 textColor=ORANGE, leading=11)),
        Paragraph('CSV: auto-dektekteras (semikolon + komma-decimal)', sml),
    ]

    two_col = Table([[left, right]], colWidths=[80*mm, 90*mm])
    two_col.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (0,-1), 0),
        ('RIGHTPADDING', (0,0), (0,-1), 6),
        ('LEFTPADDING', (1,0), (1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('LINEAFTER', (0,0), (0,-1), 0.5, BORDER),
    ]))
    story += [two_col, Spacer(1, 4*mm),
              HRFlowable(width='100%', thickness=0.5, color=BORDER),
              Spacer(1, 3*mm)]

    # ── 4 steg ────────────────────────────────────────────────────────────────
    story.append(Paragraph('4 STEG TILL ANALYS', lbl))
    story.append(Spacer(1, 2*mm))
    step_cells = []
    for num, col, title, desc in [
        ('1', ORANGE, 'VÄLJ SCENARIO',  'Välj i sidopanelen. Ändra servicenivå om det behövs.'),
        ('2', BLUE,   'LADDA UPP DATA', 'Excel/CSV med rätt kolumner, eller fyll i manuellt.'),
        ('3', RED,    'LÄSA KPI-RADEN', '"Akut inköpsbehov" = det du behöver lägga in nu.'),
        ('4', GREEN,  'EXPORTERA',      'Ladda ned Excel-rapporten och skicka till inköp.'),
    ]:
        cell = Table([[
            Table([[Paragraph(num, ParagraphStyle('n', fontName='Helvetica-Bold',
                              fontSize=13, textColor=white, alignment=TA_CENTER,
                              leading=16))]],
                  colWidths=[8*mm], rowHeights=[10*mm]),
            [Paragraph(title, ParagraphStyle('t', fontName='Helvetica-Bold', fontSize=8,
                                              textColor=col, leading=11)),
             Paragraph(desc, b)],
        ]], colWidths=[10*mm, 33*mm])
        cell.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,-1), col),
            ('BACKGROUND', (1,0), (1,-1), PALE),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 3),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('BOX', (0,0), (-1,-1), 0.5, BORDER),
        ]))
        step_cells.append(cell)
    steps_row = Table([step_cells], colWidths=[43*mm] * 4)
    steps_row.setStyle(TableStyle([
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story += [steps_row, Spacer(1, 4*mm),
              HRFlowable(width='100%', thickness=0.5, color=BORDER),
              Spacer(1, 3*mm)]

    # ── Nyckelbegrepp ─────────────────────────────────────────────────────────
    story.append(Paragraph('NYCKELBEGREPP OCH FORMLER', lbl))
    story.append(Spacer(1, 2*mm))
    gl_data = [
        ['Begrepp', 'Formel', 'Vad det betyder'],
        ['SS (Säkerhetslager)',      'z × σ_d × √LT',              'Buffert mot efterfråge-variabilitet'],
        ['ROP (Ombeställn.punkt)',   'μ_d × LT + SS',              'Saldo vid vilket ny order ska läggas'],
        ['DOS (Dagars täckning)',    'Saldo ÷ μ_d',                'Hur länge lagret räcker i dagar'],
        ['Stockout-risk',           'Saldo < ROP_nytt',           'Saldo under ombeställningspunkten → akut risk'],
        ['Akut inköpsbehov',        'max(0, ROP_ny − Saldo) × Pris', 'SEK som måste köpas in nu'],
        ['ABC (årsförbrukningsvärde)', 'μ_d × 365 × Pris',        'A = topp 80%, B = 15%, C = 5%'],
    ]
    gl_rows = [[Paragraph(c, ParagraphStyle('gl', fontName='Helvetica-Bold' if i == 0
                           else ('Courier' if j == 1 else 'Helvetica'),
                           fontSize=7.5, textColor=white if i == 0 else DARK, leading=11))
                for j, c in enumerate(row)] for i, row in enumerate(gl_data)]
    gl_t = Table(gl_rows, colWidths=[38*mm, 46*mm, 86*mm])
    gl_t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), TBL_HDR),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [white, TBL_ALT]),
        ('GRID', (0,0), (-1,-1), 0.3, BORDER),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story += [gl_t, Spacer(1, 4*mm),
              HRFlowable(width='100%', thickness=0.5, color=BORDER),
              Spacer(1, 3*mm)]

    # ── Risknivåer ────────────────────────────────────────────────────────────
    story.append(Paragraph('RISKNIVÅER', lbl))
    story.append(Spacer(1, 2*mm))
    for r_name, r_col, r_crit, r_action in [
        ('KRITISK', '#e05252', 'Saldo < ROP + ABC A',   'Akut inköp — kontakta leverantör direkt'),
        ('HÖG',     '#e0a952', 'Saldo < ROP + B/C',     'Prioriterat inköp inom 1–2 veckor'),
        ('MEDEL',   '#e0c852', 'DOS < LT×1.5',          'Bevaka och planera inköp'),
        ('LÅG',     '#52a887', 'DOS ≥ LT×1.5',          'Ingen åtgärd krävs'),
    ]:
        rr = Table([[
            Paragraph(f'<b>{r_name}</b>', ParagraphStyle('rn', fontName='Helvetica-Bold',
                       fontSize=8, textColor=white, leading=11)),
            Paragraph(r_crit, b),
            Paragraph(r_action, ParagraphStyle('ra', fontName='Helvetica-Bold', fontSize=8,
                       textColor=HexColor(r_col), leading=11)),
        ]], colWidths=[18*mm, 62*mm, 90*mm])
        rr.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,-1), HexColor(r_col)),
            ('BACKGROUND', (1,0), (-1,-1), PALE),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('BOX', (0,0), (-1,-1), 0.3, BORDER),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(rr)

    story.append(Spacer(1, 14*mm))
    doc.build(story)
    print(f'✓  Quick Start: {path}')


if __name__ == '__main__':
    build_full_manual('/Users/davidleifsson/Lagerapp/Riskkompass_Manual.pdf')
    build_quickstart('/Users/davidleifsson/Lagerapp/Riskkompass_QuickStart.pdf')
    print('\nKlart! Båda PDF-filerna skapade.')
