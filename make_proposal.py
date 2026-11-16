"""Präsentation des Lösungsansatzes als Konzept (8 Folien).

Erzeugt slides/Loesungsvorschlag.pptx: Deckblatt, Inhalt, fünf Inhaltsfolien,
Danksagung.  Der Ansatz wird als Lösungsvorschlag präsentiert, ohne
Rechenergebnisse.

Run:  .venv/bin/python make_proposal.py
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

DARK = RGBColor(0x1F, 0x3A, 0x5F)
ACCENT = RGBColor(0xE6, 0x7E, 0x00)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
LIGHT = RGBColor(0xF2, 0xF5, 0xF9)
MID = RGBColor(0xD9, 0xE2, 0xF3)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
TEXT = RGBColor(0x22, 0x22, 0x22)
GRAY = RGBColor(0x66, 0x66, 0x66)

OUT = Path("slides/Loesungsvorschlag.pptx")
TOTAL = 8


# ---------------------------------------------------------------- helpers
def text(slide, x, y, w, h, lines, size=18, color=TEXT, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, spacing=6):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    if isinstance(lines, str):
        lines = [lines]
    for n, line in enumerate(lines):
        p = tf.paragraphs[0] if n == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(spacing)
        runs = line if isinstance(line, list) else [(line, bold)]
        for t, b in runs:
            r = p.add_run()
            r.text = t
            r.font.size = Pt(size)
            r.font.bold = b
            r.font.color.rgb = color
    return box


def bullets(slide, x, y, w, h, items, size=17):
    """items: str or (head, rest) tuples; rendered as '▪ head rest'."""
    lines = []
    for it in items:
        if isinstance(it, tuple):
            lines.append([("▪  ", False), (it[0], True), (" " + it[1], False)])
        else:
            lines.append([("▪  ", False), (it, False)])
    return text(slide, x, y, w, h, lines, size=size, spacing=10)


def box(slide, x, y, w, h, label, fill=LIGHT, color=TEXT, size=14, bold=False,
        shape=MSO_SHAPE.ROUNDED_RECTANGLE, line=None):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(1.5)
    s.shadow.inherit = False
    tf = s.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Inches(0.08)
    lines = label if isinstance(label, list) else [label]
    for n, line in enumerate(lines):
        p = tf.paragraphs[0] if n == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size if n == 0 else size - 3)
        r.font.bold = bold if n == 0 else False
        r.font.color.rgb = color
    return s


def arrow(slide, x1, y1, x2, y2, color=GRAY, width=2.0):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(width)
    ln = c.line._get_or_add_ln()
    tail = ln.makeelement("{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd",
                          {"type": "triangle", "w": "med", "len": "med"})
    ln.append(tail)
    return c


def content_slide(prs, number, title, subtitle=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(1.05))
    bar.fill.solid()
    bar.fill.fore_color.rgb = DARK
    bar.line.fill.background()
    text(slide, 0.6, 0.18, 11.0, 0.7, title, size=28, color=WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    if number:
        text(slide, 11.6, 0.18, 1.2, 0.7, f"{number:02d}", size=28, color=ACCENT, bold=True,
             align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
    if subtitle:
        text(slide, 0.6, 1.2, 12.1, 0.5, subtitle, size=16, color=GRAY)
    footer(prs, slide)
    return slide


def footer(prs, slide):
    idx = len(prs.slides)
    text(slide, 0.6, 7.0, 9.0, 0.35, "Mini-Supermarkt-Netz · Lösungsvorschlag", size=10, color=GRAY)
    text(slide, 11.3, 7.0, 1.5, 0.35, f"{idx} / {TOTAL}", size=10, color=GRAY, align=PP_ALIGN.RIGHT)


def notes(slide, txt):
    slide.notes_slide.notes_text_frame.text = txt


def dark_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = DARK
    bg.line.fill.background()
    stripe = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.9), Inches(3.55), Inches(1.4), Inches(0.08))
    stripe.fill.solid()
    stripe.fill.fore_color.rgb = ACCENT
    stripe.line.fill.background()
    return slide


# ---------------------------------------------------------------- slides
def main() -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # 1 Deckblatt -------------------------------------------------------
    s = dark_slide(prs)
    text(s, 0.9, 1.9, 11.5, 1.0, "Mini-Supermarkt-Netz", size=48, color=WHITE, bold=True)
    text(s, 0.9, 2.75, 11.5, 0.7, "Lösungsvorschlag für die gemeinsame Standort- und Tourenplanung",
         size=24, color=MID)
    text(s, 0.9, 4.0, 11.5, 1.4, ["Supply Chain Management · Projektarbeit",
                                  "Gruppe: [Namen eintragen]  ·  [Datum]"], size=18, color=MID)
    notes(s, "Begrüßung, Vorstellung der Gruppe. Wir stellen heute unser Konzept vor, "
             "wie man das Netz aus einem Guss planen könnte.")

    # 2 Inhalt -------------------------------------------------------------
    s = content_slide(prs, 0, "Inhalt")
    items = [
        ("Ausgangslage", "Welche Entscheidungen das Netz verlangt"),
        ("Grundidee", "Erst Touren sammeln, dann auswählen"),
        ("Das Auswahlmodell", "Variablen, Regeln und ein wichtiges Detail"),
        ("Depotwahl", "Das beste Depot finden, ohne alle durchzurechnen"),
        ("Robustheit, Grenzen und Ausblick", "Was der Ansatz leisten kann – und was nicht"),
    ]
    for n, (head, sub) in enumerate(items):
        y = 1.55 + n * 1.0
        box(s, 0.9, y, 0.75, 0.75, f"{n+1}", fill=DARK, color=WHITE, size=22, bold=True,
            shape=MSO_SHAPE.OVAL)
        text(s, 1.9, y - 0.02, 9.5, 0.45, head, size=22, bold=True, color=DARK)
        text(s, 1.9, y + 0.38, 9.5, 0.4, sub, size=15, color=GRAY)
    notes(s, "Kurzer Überblick über die fünf Teile.")

    # 3 Ausgangslage ---------------------------------------------------------
    s = content_slide(prs, 1, "Ausgangslage: fünf Entscheidungen, die zusammenhängen",
                      "671 Regionen, Entfernungsmatrix, Kosten- und Ertragsdaten je Region")
    # network diagram
    box(s, 0.7, 3.2, 1.6, 0.9, ["Zentrallager", "(Depot)"], fill=DARK, color=WHITE, bold=True, size=15)
    box(s, 3.4, 2.1, 1.6, 0.8, ["Satellit A"], fill=MID, color=DARK, bold=True)
    box(s, 3.4, 4.4, 1.6, 0.8, ["Satellit B"], fill=MID, color=DARK, bold=True)
    arrow(s, 2.3, 3.45, 3.4, 2.5, color=DARK)
    arrow(s, 2.3, 3.85, 3.4, 4.8, color=DARK)
    text(s, 1.55, 2.45, 1.5, 0.4, "Lkw 1×/Woche", size=11, color=GRAY, align=PP_ALIGN.RIGHT)
    text(s, 1.55, 4.45, 1.5, 0.4, "Lkw 1×/Woche", size=11, color=GRAY, align=PP_ALIGN.RIGHT)
    for k, (x, y) in enumerate([(6.0, 1.7), (6.0, 2.7), (6.0, 4.0), (6.0, 5.0), (0.95, 5.6)]):
        box(s, x, y, 1.1, 0.6, "Markt", fill=LIGHT, color=TEXT, size=12, line=GREEN)
    for y in (2.0, 3.0):
        arrow(s, 5.0, 2.5, 6.0, y, color=GREEN, width=1.5)
    for y in (4.3, 5.3):
        arrow(s, 5.0, 4.8, 6.0, y, color=GREEN, width=1.5)
    arrow(s, 1.5, 4.1, 1.5, 5.6, color=GREEN, width=1.5)
    text(s, 1.6, 4.95, 2.2, 0.4, "Transporter (direkt)", size=11, color=GREEN)
    text(s, 4.95, 3.4, 2.4, 0.4, "Transporter-Touren", size=11, color=GREEN)
    bullets(s, 7.7, 1.75, 5.2, 3.6, [
        ("Depot:", "in welcher Region?"),
        ("Satelliten:", "wie viele und wo?"),
        ("Märkte:", "welche lohnen sich?"),
        ("Zuordnung:", "welches Lager beliefert welchen Markt?"),
        ("Touren:", "welche Rundfahrten pro Woche?"),
    ], size=17)
    box(s, 7.7, 5.0, 5.1, 1.55,
        ["Ziel: Jahresgewinn maximieren",
         "Rohertrag − Markt-, Lager-, Lkw- und Transporterkosten",
         "jeder Markt 3× pro Woche · Tour ≤ 8 h (50 km/h + 30 min je Markt)"],
        fill=LIGHT, color=DARK, size=17, bold=True, line=ACCENT)
    notes(s, "Die Entscheidungen hängen voneinander ab: Ein Satellit lohnt sich nur, wenn genug "
             "Märkte in der Nähe sind; ob ein Markt sich lohnt, hängt davon ab, wie teuer seine "
             "Belieferung ist. Deshalb wollen wir sie nicht nacheinander, sondern gemeinsam treffen.")

    # 4 Grundidee -------------------------------------------------------------
    s = content_slide(prs, 2, "Grundidee: erst Touren sammeln, dann auswählen",
                      "Zwei Stufen trennen das schwierige Tourenproblem von der Netzentscheidung")
    steps = [
        (["Daten", "Regionen, Distanzen, Kosten"], LIGHT, DARK),
        (["Stufe 1: Tourenkatalog", "viele zulässige Rundfahrten je möglichem Lager"], MID, DARK),
        (["Stufe 2: Auswahlmodell", "wählt Lager, Märkte und Touren gleichzeitig"], DARK, WHITE),
        (["Netz", "Standorte, Zuordnung, Wochentouren"], LIGHT, DARK),
    ]
    for n, (lbl, fill, col) in enumerate(steps):
        x = 0.7 + n * 3.15
        box(s, x, 1.95, 2.65, 1.35, lbl, fill=fill, color=col, size=16, bold=True,
            line=None if fill != LIGHT else DARK)
        if n < 3:
            arrow(s, x + 2.65, 2.62, x + 3.15, 2.62, color=DARK, width=2.5)
    text(s, 0.7, 3.65, 6.0, 0.45, "Stufe 1 – Tourenkatalog", size=19, bold=True, color=DARK)
    bullets(s, 0.7, 4.15, 6.0, 2.7, [
        ("Bausteine:", "Einzeltouren, Zweiertouren benachbarter Märkte, Touren aus dem Savings-Verfahren"),
        ("Nur zulässige Touren:", "8-Stunden-Grenze wird beim Erzeugen geprüft"),
        ("Kosten je Tour", "einmal exakt berechnen (kurze Touren optimal reihen)"),
    ], size=17)
    text(s, 7.0, 3.65, 5.8, 0.45, "Stufe 2 – Auswahl", size=19, bold=True, color=DARK)
    bullets(s, 7.0, 4.15, 5.8, 2.7, [
        ("Ein lineares Modell", "entscheidet über alles gleichzeitig"),
        ("Vorteil:", "Zeitgrenze und Tourlänge stecken schon im Katalog – das Modell bleibt einfach"),
        ("Lösbar", "mit Standard-Solvern, z. B. dem Open-Source-Solver HiGHS"),
    ], size=17)
    notes(s, "Das klassische Vorgehen wäre: Standorte festlegen, dann Touren planen. Wir schlagen "
             "vor, umgekehrt zu denken: Man sammelt vorab einen großen Katalog sinnvoller Touren "
             "und lässt dann ein Optimierungsmodell die beste Kombination auswählen "
             "(Set-Partitioning-Ansatz).")

    # 5 Auswahlmodell ------------------------------------------------------------
    s = content_slide(prs, 3, "Das Auswahlmodell", "Ein gemischt-ganzzahliges lineares Programm (MILP)")
    rows = [
        ("Variable", "Bedeutung"),
        ("y_i ∈ {0,1}", "Markt i wird eröffnet"),
        ("z_w ∈ {0,1}", "Lager w wird eröffnet (Depot oder Satellit)"),
        ("a_iw ∈ {0,1}", "Markt i wird von Lager w beliefert"),
        ("λ_r ∈ {0,…,3}", "Tour r wird so oft pro Woche gefahren"),
    ]
    tbl = s.shapes.add_table(len(rows), 2, Inches(0.7), Inches(1.85), Inches(6.2), Inches(2.6)).table
    tbl.columns[0].width = Inches(1.9)
    tbl.columns[1].width = Inches(4.3)
    for r, (a, b) in enumerate(rows):
        for c, val in enumerate((a, b)):
            cell = tbl.cell(r, c)
            cell.text = val
            p = cell.text_frame.paragraphs[0]
            p.font.size = Pt(15)
            p.font.bold = r == 0
            p.font.color.rgb = WHITE if r == 0 else TEXT
            cell.fill.solid()
            cell.fill.fore_color.rgb = DARK if r == 0 else (LIGHT if r % 2 else WHITE)
    text(s, 0.7, 4.75, 6.2, 0.45, "Regeln (Nebenbedingungen)", size=19, bold=True, color=DARK)
    bullets(s, 0.7, 5.2, 6.2, 1.8, [
        "Jeder eröffnete Markt wird genau 3× pro Woche angefahren",
        "Jeder eröffnete Markt gehört zu genau einem Lager",
        "Touren nur zu den Märkten des eigenen Lagers",
    ], size=15)
    text(s, 7.4, 1.85, 5.4, 0.45, "Zielfunktion", size=19, bold=True, color=DARK)
    box(s, 7.4, 2.35, 5.4, 1.1,
        ["max  Σ Margen − Lager- − Lkw- − Tourkosten"],
        fill=LIGHT, color=DARK, size=15, bold=True, line=DARK)
    box(s, 7.4, 3.85, 5.4, 2.85,
        ["Detail mit großer Wirkung:  a_iw ≤ z_w",
         "„Ein Markt darf nur einem geöffneten Lager zugeordnet sein.“ "
         "Logisch selbstverständlich – aber explizit formuliert macht diese Regel die "
         "LP-Relaxation deutlich schärfer als eine einzelne Big-M-Bedingung pro Lager. "
         "Der Solver kann Teilbäume dann früher verwerfen und Optimalität schneller beweisen."],
        fill=WHITE, color=DARK, size=17, bold=True, line=ACCENT)
    notes(s, "Die Variablen und Regeln sind bewusst einfach. Wichtig ist die Formulierung: Die "
             "Kopplung zwischen Zuordnung und Lageröffnung sollte je Markt-Lager-Paar formuliert "
             "werden, nicht nur als eine große Sammelbedingung pro Lager. Beide Varianten sind "
             "für ganzzahlige Lösungen gleichwertig, aber die feinere liefert viel bessere "
             "Schranken.")

    # 6 Depotwahl ------------------------------------------------------------------
    s = content_slide(prs, 4, "Depotwahl: das beste Depot finden, ohne alle durchzurechnen",
                      "Das Depot nicht vorab festlegen, sondern mit Schranken systematisch eingrenzen")
    funnel = [
        (["Alle Regionen", "als mögliche Depots"], 5.6, MID, DARK),
        (["Schranke je Depot", "schnelle LP-Relaxation: „besser als X geht es nicht“"], 4.6, DARK, WHITE),
        (["Exakt rechnen", "nur Depots, deren Schranke das Beste noch schlagen kann"], 3.6, DARK, WHITE),
        (["Bestes Depot", "mit Optimalitätsnachweis (für den Katalog)"], 2.6, ACCENT, WHITE),
    ]
    for n, (lbl, w, fill, col) in enumerate(funnel):
        x = 0.7 + (5.6 - w) / 2
        box(s, x, 1.85 + n * 1.25, w, 1.0, lbl, fill=fill, color=col, size=15, bold=True)
    bullets(s, 6.8, 1.85, 6.1, 5.0, [
        ("Warum nicht vorab wählen?", "Ein Depot, das ohne Satelliten am besten ist, ist es mit "
         "Satelliten nicht unbedingt – die Entscheidungen beeinflussen sich gegenseitig."),
        ("Schlüsselbeobachtung:", "Der Tourenkatalog hängt nicht vom Depot ab. Ein Katalog reicht; "
         "pro Depot ändern sich nur die Kosten der Lagervariablen."),
        ("Lagerkandidaten ausdünnen:", "Eine Region ist überflüssig, wenn eine andere nicht teurer "
         "und zu keinem Markt weiter entfernt ist (Dominanz) – sicher, ohne Optimum zu verlieren."),
    ], size=16)
    notes(s, "Statt das Depot heuristisch festzulegen, würden wir für jedes mögliche Depot eine "
             "obere Schranke berechnen. Nur Depots, deren Schranke über der besten bekannten Lösung "
             "liegt, müssen exakt gelöst werden. Damit wäre die Depotwahl nachweisbar optimal, "
             "ohne hunderte große Modelle zu lösen.")

    # 7 Robustheit, Grenzen, Ausblick ------------------------------------------------
    s = content_slide(prs, 5, "Robustheit, Grenzen und Ausblick")
    cols = [
        ("Robustheit prüfen", GREEN, [
            ("Pessimistisch:", "Rohertrag −10 %, km-Kosten +10 %"),
            ("Optimistisch:", "Rohertrag +10 %, km-Kosten −10 %"),
            ("Zwei Fragen:", "Wie schlägt sich das geplante Netz? Wie sähe das Szenario-Optimum aus?"),
        ]),
        ("Grenzen", ACCENT, [
            ("Tourenkatalog:", "Optimal ist das Ergebnis nur bezogen auf die erzeugten Touren"),
            ("Vereinfachungen:", "keine Kapazitäten, keine Liefertage, 52 gleiche Wochen"),
            ("Daten:", "Erträge und Kosten sind Erwartungswerte"),
        ]),
        ("Ausblick", DARK, [
            ("Spaltengenerierung:", "fehlende gute Touren gezielt nachgenerieren → Nachweis über alle Touren"),
            ("Erweiterungen:", "Kapazitäten, feste Liefertage, mehrere Perioden"),
            ("Visualisierung:", "interaktive Karte für die Entscheider"),
        ]),
    ]
    for n, (head, color, items) in enumerate(cols):
        x = 0.6 + n * 4.15
        bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(1.45), Inches(3.9), Inches(0.08))
        bar.fill.solid()
        bar.fill.fore_color.rgb = color
        bar.line.fill.background()
        text(s, x, 1.6, 3.9, 0.5, head, size=21, bold=True, color=color)
        bullets(s, x, 2.25, 3.9, 3.2, items, size=16)
    box(s, 0.6, 5.55, 12.2, 1.15,
        ["Unser Vorschlag in einem Satz",
         "Touren vorab sammeln, das Netz in einem Modell gemeinsam auswählen "
         "und das Depot über Schranken nachweisbar eingrenzen."],
        fill=LIGHT, color=DARK, size=18, bold=True, line=DARK)
    notes(s, "Zum Schluss: Wie robust wäre eine Lösung, wo liegen die Grenzen des Ansatzes, "
             "und wie könnte man ihn weiterentwickeln. Die wichtigste Erweiterung wäre die "
             "Spaltengenerierung, um nicht vom vorab erzeugten Tourenkatalog abhängig zu sein.")

    # 8 Danke ------------------------------------------------------------------------
    s = dark_slide(prs)
    text(s, 0.9, 2.3, 11.5, 1.0, "Vielen Dank für Ihre Aufmerksamkeit!", size=44, color=WHITE, bold=True)
    text(s, 0.9, 4.0, 11.5, 0.8, "Wir freuen uns auf Ihre Fragen und Anmerkungen.", size=22, color=MID)
    notes(s, "Dank und Überleitung zur Diskussion.")

    assert len(prs.slides) == TOTAL
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"saved {OUT} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
