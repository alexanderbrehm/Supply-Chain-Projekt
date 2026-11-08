"""Create figures and the final presentation from the result JSON files.

Run after ``run_baseline.py``, ``run_milp.py`` and ``run_robustness.py``:

    .venv/bin/python make_report.py --optimized results/milp_200.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

from scm.analysis import (
    plot_network,
    plot_profit_bridge,
    plot_scenario_bars,
    profit_bridge,
)
from scm.data import load_data
from scm.io import load_network, network_from_dict, save_json

# --------------------------------------------------------------------------- style
DARK = RGBColor(0x1F, 0x3A, 0x5F)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
ORANGE = RGBColor(0xE6, 0x7E, 0x00)
RED = RGBColor(0xC6, 0x28, 0x28)
GRAY = RGBColor(0x66, 0x66, 0x66)
LIGHT = RGBColor(0xF2, 0xF5, 0xF9)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def _money(value: float) -> str:
    return f"{value/1e6:.3f}".replace(".", ",") + " Mio. EUR"


def _pct(value: float) -> str:
    return f"{value:.2%}".replace(".", ",").replace("%", " %")


def _eur(value: float, sign: bool = False) -> str:
    spec = f"{'+' if sign and abs(value) >= 0.5 else ''},.0f"
    return f"{format(value, spec)} EUR".replace(",", ".")


def _add_slide(prs: Presentation, title: str, subtitle: str | None = None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    # top bar
    bar = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(0.12))
    bar.fill.solid()
    bar.fill.fore_color.rgb = DARK
    bar.line.fill.background()
    # title
    box = slide.shapes.add_textbox(Inches(0.55), Inches(0.35), Inches(12.2), Inches(0.8))
    tf = box.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = DARK
    if subtitle:
        sub = slide.shapes.add_textbox(Inches(0.58), Inches(1.05), Inches(12.0), Inches(0.5))
        stf = sub.text_frame
        stf.clear()
        sp = stf.paragraphs[0]
        sp.text = subtitle
        sp.font.size = Pt(14)
        sp.font.color.rgb = GRAY
    return slide


def _add_footer(slide, text: str) -> None:
    box = slide.shapes.add_textbox(Inches(0.55), Inches(7.08), Inches(12.2), Inches(0.28))
    tf = box.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(9)
    p.font.color.rgb = GRAY


def _add_bullets(
    slide,
    items: list[str],
    *,
    left: float = 0.7,
    top: float = 1.45,
    width: float = 12.0,
    height: float = 5.3,
    size: int = 17,
    color: RGBColor = RGBColor(0x22, 0x22, 0x22),
) -> None:
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for idx, item in enumerate(items):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = item
        p.level = 0
        p.font.size = Pt(size)
        p.font.color.rgb = color
        p.space_after = Pt(7)
        if item.startswith("•"):
            p.text = item[1:].strip()
            p.level = 0
            p.font.size = Pt(size)
    # use real bullet formatting
    for p in tf.paragraphs:
        pPr = p._p.get_or_add_pPr()
        pPr.set("marL", str(Inches(0.25)))
        pPr.set("indent", str(-Inches(0.25)))
        bu = pPr.makeelement(
            "{http://schemas.openxmlformats.org/drawingml/2006/main}buChar",
            {"char": "•"},
        )
        pPr.append(bu)


def _add_image_fit(slide, path: str | Path, left: float, top: float, width: float, height: float) -> None:
    from PIL import Image

    with Image.open(path) as img:
        iw, ih = img.size
    scale = min(width / iw, height / ih)
    w, h = iw * scale, ih * scale
    x = left + (width - w) / 2
    y = top + (height - h) / 2
    slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))


def _add_table(
    slide,
    rows: list[list[str]],
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    font_size: int = 12,
    header: bool = True,
) -> None:
    shape = slide.shapes.add_table(len(rows), len(rows[0]), Inches(left), Inches(top), Inches(width), Inches(height))
    table = shape.table
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.text = str(value)
            cell.margin_left = Inches(0.05)
            cell.margin_right = Inches(0.05)
            cell.margin_top = Inches(0.02)
            cell.margin_bottom = Inches(0.02)
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(font_size)
                p.font.color.rgb = WHITE if (header and r == 0) else RGBColor(0x22, 0x22, 0x22)
                p.font.bold = header and r == 0
                p.alignment = PP_ALIGN.LEFT
            cell.fill.solid()
            cell.fill.fore_color.rgb = DARK if (header and r == 0) else LIGHT
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="results/baseline.json")
    ap.add_argument("--optimized", default="results/milp_best.json")
    ap.add_argument("--robustness", default="results/robustness_summary.json")
    ap.add_argument("--out", default="slides/Mini-Supermarkt-Netz.pptx")
    args = ap.parse_args()

    data = load_data("Projektdateien")
    baseline_raw = json.loads(Path(args.baseline).read_text())
    optimized_raw = json.loads(Path(args.optimized).read_text())
    baseline_net = network_from_dict(baseline_raw["network"])
    optimized_net = load_network(args.optimized)
    baseline = baseline_raw["breakdown"]
    optimized = optimized_raw["breakdown"]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig_dir = out.parent

    # ------------------------------------------------------------------ figures
    plot_profit_bridge(baseline, optimized, fig_dir / "gewinnbruecke.png")
    plot_network(
        data,
        optimized_net,
        fig_dir / "netzwerk.png",
        title=f"Optimiertes Netz – {_money(optimized['profit'])} Jahresgewinn",
    )
    plot_network(
        data,
        baseline_net,
        fig_dir / "baseline_netzwerk.png",
        title=f"Baseline-Netz – {_money(baseline['profit'])} Jahresgewinn",
    )

    robustness: dict[str, dict[str, float]] = {}
    if Path(args.robustness).exists():
        robustness = json.loads(Path(args.robustness).read_text())
        plot_scenario_bars(robustness, fig_dir / "robustheit.png")

    bridge = profit_bridge(baseline, optimized)
    sizes = Counter(
        len(r) for routes in optimized_net.routes.values() for r in routes
    )
    n_patterns = len(
        {
            (w, frozenset(route))
            for w, routes in optimized_net.routes.items()
            for route in routes
        }
    )
    save_json(
        fig_dir / "kennzahlen.json",
        {
            "baseline": baseline,
            "optimized": optimized,
            "bridge": bridge,
            "route_size_distribution": dict(sorted(sizes.items())),
            "n_patterns": n_patterns,
            "n_candidates": len(optimized_raw.get("candidates", [])),
            "mip_gap": optimized_raw.get("mip_gap"),
            "runtime_s": optimized_raw.get("runtime_s"),
        },
    )

    # ------------------------------------------------------------------ slides
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    n_slides = 0

    # 1 title
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = DARK
    bg.line.fill.background()
    box = slide.shapes.add_textbox(Inches(0.9), Inches(2.0), Inches(11.5), Inches(1.4))
    tf = box.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = "Mini-Supermarkt-Netz"
    p.font.size = Pt(46)
    p.font.bold = True
    p.font.color.rgb = WHITE
    p = tf.add_paragraph()
    p.text = "Standort- und Routenoptimierung mit HiGHS"
    p.font.size = Pt(24)
    p.font.color.rgb = RGBColor(0xD9, 0xE2, 0xF3)
    box = slide.shapes.add_textbox(Inches(0.9), Inches(4.2), Inches(11.5), Inches(1.0))
    tf = box.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = "Supply Chain Management – Projektpräsentation"
    p.font.size = Pt(16)
    p.font.color.rgb = RGBColor(0xD9, 0xE2, 0xF3)
    n_slides += 1

    # 2 data
    slide = _add_slide(prs, "Aufgabe und Datenbasis")
    _add_bullets(
        slide,
        [
            f"671 Regionen in Deutschland, davon {len(data.stores)} mit positivem Marktdeckungsbeitrag.",
            f"Summe der positiven Marktmargen: {_money(sum(data.margin(i) for i in data.stores))} pro Jahr.",
            "Entscheidungen: Depot (alle 671 Regionen), optionale Satelliten, geöffnete Märkte, Zuordnung und Wochenrouten.",
            "Ziel: Jahresgewinn maximieren – Rohertrag minus Markt-, Lager-, Lkw- und Transporterkosten.",
            "Restriktion: jede Route ist eine Rundtour mit max. 8 h Fahr- plus Servicezeit.",
        ],
        size=20,
    )
    _add_footer(slide, "Daten: Regions.csv, DistanceMatrix.csv, Parameter.csv")
    n_slides += 1

    # 3 assumptions
    slide = _add_slide(prs, "Annahmen")
    _add_bullets(
        slide,
        [
            "52 identische Wochen pro Jahr; jeder geöffnete Markt wird genau dreimal pro Woche beliefert.",
            "Ein Markt höchstens einmal pro Route; die drei Wochenlieferungen dürfen über verschiedene Routen erfolgen.",
            "Route: Lager → Märkte → Lager; Fahrzeit = Distanz / 50 km/h, plus 30 min Service pro Markt.",
            "Lkw: genau eine Hin- und Rückfahrt pro Woche und Satellit; Fixkosten pro Fahrt bleiben in Szenarien konstant.",
            "Keine Fahrzeugkapazitäten, keine Bestandsrestriktionen; jeder Markt von genau einem Lager.",
        ],
        size=19,
    )
    _add_footer(slide, "Alle Kosten in EUR pro Jahr, sofern nicht anders angegeben.")
    n_slides += 1

    # 4 approach
    slide = _add_slide(prs, "Lösungsansatz: Baseline + MILP")
    _add_bullets(
        slide,
        [
            "Baseline: alle 671 möglichen Depots mit Savings-Routing bewerten, dann Märkte streichen und Satelliten greedy ergänzen.",
            "Optimierung: Set-Partitioning-MILP mit HiGHS – Satelliten, Märkte, Zuordnung und Routen simultan; Depot per LP-Schranken über alle 671 Regionen.",
            "Routenpool: Savings-Routen, Singletons, kurze Zweier-Routen für jede der 671 Regionen als Lager.",
            "Jeder Markt: genau 3 Besuche/Woche; Routenmultiplizität 0–3; eine Route kann also bis zu dreimal gefahren werden.",
            "Zwei-Stufen-Ansatz: schnelle, erklärbare Baseline als Referenz; MILP für die systematische Verbesserung.",
        ],
        size=19,
    )
    _add_footer(slide, "HiGHS 1.15.1, highspy; Python 3.12")
    n_slides += 1

    # 5 baseline
    slide = _add_slide(prs, "Baseline-Netz")
    rows = [
        ["Kennzahl", "Wert"],
        ["Depot", str(baseline_net.depot)],
        ["Satelliten", ", ".join(map(str, sorted(baseline_net.satellites))) or "–"],
        ["Geöffnete Märkte", str(len(baseline_net.stores))],
        ["Fahrten / Woche", f"{baseline['n_routes']:.0f}"],
        ["Jahresgewinn", _money(baseline["profit"])],
    ]
    _add_table(slide, rows, left=0.7, top=1.5, width=6.2, height=3.5, font_size=14)
    _add_image_fit(slide, fig_dir / "baseline_netzwerk.png", 6.9, 1.35, 5.8, 5.4)
    _add_footer(slide, "Baseline: analytisch, ohne MILP; dient als Referenz.")
    n_slides += 1

    # 6 MILP
    slide = _add_slide(prs, "Optimierung: Set-Partitioning-MILP")
    pool_label = f"{optimized_raw.get('n_routes_pool', 0):,}".replace(",", ".")
    _add_bullets(
        slide,
        [
            "Variablen: y (Markt offen), z (Lager offen), a (Zuordnung), λ (Routenhäufigkeit 0–3).",
            "Nebenbedingungen: 3 Besuche pro offenem Markt, genau eine Lagerzuordnung, Zuordnung nur zu offenen Lagern (a ≤ z).",
            f"Routenpool: {pool_label} Routen; Lagerkandidaten: {len(optimized_raw.get('candidates', [])) or '–'} Regionen.",
            "Starke Kopplung a ≤ z: LP-Schranke fällt von 3,16 auf 2,40 Mio. EUR (= Optimum, 202er-Pool).",
            f"Depotwahl: LP-Schranke für jedes Depot, danach exaktes MILP; HiGHS-Status {optimized_raw.get('status', '–')}, Gap {_pct(optimized_raw.get('mip_gap', 0))}, Laufzeit {optimized_raw.get('runtime_s', 0):.0f} s.",
            "Das Optimum gilt für den erzeugten Routenpool – über alle Depots und alle Lagerregionen.",
        ],
        size=18,
    )
    _add_footer(slide, "Offen bleibt nur der Routenpool: ein Beweis über alle Routen braucht Column Generation.")
    n_slides += 1

    # 7 network map
    slide = _add_slide(prs, "Optimiertes Netzwerk")
    _add_image_fit(slide, fig_dir / "netzwerk.png", 0.45, 1.25, 7.6, 5.8)
    _add_bullets(
        slide,
        [
            f"Depot: {optimized_net.depot}",
            f"Satelliten: {', '.join(map(str, sorted(optimized_net.satellites))) or '–'}",
            f"Märkte: {len(optimized_net.stores)}",
            f"Fahrten/Woche: {optimized['n_routes']:.0f} ({n_patterns} Routenmuster)",
            f"Jahresgewinn: {_money(optimized['profit'])}",
        ],
        left=8.3,
        top=1.6,
        width=4.5,
        height=4.8,
        size=16,
    )
    _add_footer(slide, "Linien: Wochenrouten; Sterne: Depot; Quadrate: Satelliten; Punkte: Märkte.")
    n_slides += 1

    # 8 profit bridge
    slide = _add_slide(prs, "Gewinnbrücke: Baseline → Optimierung")
    _add_image_fit(slide, fig_dir / "gewinnbruecke.png", 0.45, 1.25, 8.2, 5.7)
    _add_bullets(
        slide,
        [
            f"Baseline: {_money(baseline['profit'])}",
            f"Optimiert: {_money(optimized['profit'])}",
            f"Delta: {_eur(optimized['profit'] - baseline['profit'], sign=True)} "
            f"({_pct((optimized['profit'] - baseline['profit']) / baseline['profit'])})",
            "Treiber: bessere Standort-/Satellitenwahl, geringere Marktkosten, weniger Leerkilometer.",
        ],
        left=8.9,
        top=1.6,
        width=4.0,
        height=4.8,
        size=15,
    )
    _add_footer(slide, "Positive Balken erhöhen den Gewinn, negative senken ihn.")
    n_slides += 1

    # 9 route structure
    slide = _add_slide(prs, "Routenstruktur und Logistik")
    rows = [["Routengröße", "Anzahl Fahrten"]]
    for size, count in sorted(sizes.items()):
        rows.append([str(size), str(count)])
    _add_table(slide, rows, left=0.7, top=1.5, width=4.8, height=4.2, font_size=12)
    _add_bullets(
        slide,
        [
            f"Fahrten/Woche: {optimized['n_routes']:.0f} ({n_patterns} Muster)",
            f"Routen-km/Woche: {optimized['route_km_per_week']:,.0f} km".replace(",", "."),
            f"Routen-km/Jahr: {optimized['annual_route_km']/1e6:.2f} Mio. km".replace(".", ",", 1),
            f"Transporterkosten: {_money(optimized['transporter_costs'])}",
            f"Lkw-Kosten: {_money(optimized['truck_costs'])}",
            "Große Routen senken die Fixkosten pro Markt, sind aber nur bei kurzen Distanzen zulässig.",
        ],
        left=5.9,
        top=1.5,
        width=6.8,
        height=5.0,
        size=16,
    )
    _add_footer(slide, "Fahrt = eine Rundtour; ein Routenmuster kann 1–3-mal pro Woche gefahren werden.")
    n_slides += 1

    # 10 robustness table
    slide = _add_slide(prs, "Robustheit: pessimistisch und optimistisch")
    if robustness:
        rows = [["Szenario", "Bestehend", "Neu optimiert", "Delta", "Märkte", "Satelliten"]]
        for name, s in robustness.items():
            rows.append(
                [
                    name.capitalize(),
                    _money(s["existing_profit"]),
                    _money(s["optimized_profit"]),
                    _eur(s["delta"], sign=True),
                    f"{s['existing_stores']:.0f} → {s['optimized_stores']}",
                    f"{s['existing_satellites']:.0f} → {s['optimized_satellites']}",
                ]
            )
        _add_table(slide, rows, left=0.55, top=1.5, width=12.2, height=2.6, font_size=12)
        _add_image_fit(slide, fig_dir / "robustheit.png", 0.6, 4.1, 7.2, 2.8)
        gap_text = ", ".join(
            f"{name.capitalize()} {_pct(s.get('mip_gap', 0))}"
            for name, s in robustness.items()
        )
        _add_bullets(
            slide,
            [
                "Pessimistisch: Rohertrag −10 %, km-Kosten +10 %.",
                "Optimistisch: Rohertrag +10 %, km-Kosten −10 %.",
                "Fixkosten pro Fahrt/Route bleiben unverändert.",
                f"MIP-Gap: {gap_text}; Depot frei über alle Regionen.",
            ],
            left=8.1,
            top=4.1,
            width=4.8,
            height=2.7,
            size=12,
        )
    else:
        _add_bullets(slide, ["Robustheitsergebnisse noch nicht vorhanden."], size=20)
    _add_footer(slide, "Bestehendes Netz wird mit unveränderten Standorten/Routen neu bewertet; Reoptimierung mit ausgewiesenem Gap.")
    n_slides += 1

    # 11 robustness insights
    slide = _add_slide(prs, "Robustheit: Was ändert sich?")
    if robustness:
        items = []
        for name, s in robustness.items():
            items.append(
                f"{name.capitalize()}: Netz {'identisch' if s['network_identical'] else 'verändert'}; "
                f"Märkte {s['existing_stores']:.0f} → {s['optimized_stores']}, "
                f"Satelliten {s['existing_satellites']:.0f} → {s['optimized_satellites']}; "
                f"Delta {_eur(s['delta'], sign=True)}; Status {s.get('status', '–')}, Gap {_pct(s.get('mip_gap', 0))}."
            )
            cross = s.get("cross_check")
            if cross:
                items.append(
                    f"Gegenprobe {name}: {cross['candidate_count']} Kandidaten, "
                    f"gleiche Lösung, Gap {_pct(cross['mip_gap'])} ({cross['status']})."
                )
        items += [
            "Das bestehende Netz bleibt unter beiden Szenarien profitabel.",
            "Die Reoptimierung zeigt, ob weniger Märkte oder andere Satelliten besser wären.",
            "Fixkosten bleiben konstant – die Sensitivität kommt aus Rohertrag und km-Kosten.",
        ]
        _add_bullets(slide, items, size=17)
    else:
        _add_bullets(slide, ["Robustheitsergebnisse noch nicht vorhanden."], size=20)
    _add_footer(slide, f"Vergleich: bestehendes Netz (Depot {optimized_net.depot}) vs. Reoptimierung auf Szenariodaten mit freiem Depot.")
    n_slides += 1

    # 12 conclusion
    slide = _add_slide(prs, "Fazit und Grenzen")
    _add_bullets(
        slide,
        [
            f"Die Optimierung steigert den Jahresgewinn von {_money(baseline['profit'])} auf {_money(optimized['profit'])}.",
            f"Zertifiziertes Optimum für den Routenpool über alle 671 Depots und Lager (Gap 0 %, {optimized_raw.get('runtime_s', 0):.0f} s).",
            f"Depot {optimized_net.depot} statt 379: Die Depotwahl ohne Satelliten (Baseline) führte in die Irre.",
            "Grenze: Kein Beweis über alle theoretisch möglichen Routen; der Routenpool bleibt eine Restriktion.",
            "Nächste Schritte: Column Generation / Branch-and-Price, Kapazitäten, weitere Szenarien, interaktive Karte.",
        ],
        size=19,
    )
    _add_footer(slide, f"Präsentation: {n_slides + 1} Folien (Maximum 12).")
    n_slides += 1

    prs.save(out)
    print(f"saved {out} ({n_slides} slides)")


if __name__ == "__main__":
    main()
