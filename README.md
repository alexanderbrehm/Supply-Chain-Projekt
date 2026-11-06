# Mini-Supermarkt-Netz – Supply-Chain-Optimierung

Ganzheitliches Optimierungsprojekt für ein deutsches Mini-Supermarkt-Netz:
Standortwahl, Satellitenlager, Märkte, Lieferzuordnung und Wochenrouten werden
gemeinsam geplant.  Als Solver wird **HiGHS** über `highspy` verwendet.

## 1. Schnellstart

Voraussetzungen: Python 3.12 und [`uv`](https://docs.astral.sh/uv/).

```bash
cd "/home/alexander/Schreibtisch/supply chain management"
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Die drei Eingabedateien liegen in `Projektdateien/`:

* `Regions.csv`
* `DistanceMatrix.csv`
* `Parameter.csv`

### Baseline berechnen

```bash
.venv/bin/python run_baseline.py
```

Ergebnis: `results/baseline.json` (Netz + Gewinnaufschlüsselung).

### Sensitivitätslauf (202 Kandidaten) berechnen

```bash
.venv/bin/python run_milp.py --candidates 200 --time-limit 900 --out results/milp_200
```

Wichtige Optionen:

| Option | Bedeutung |
|---|---|
| `--candidates N` | Top-N der heuristisch bewerteten Lagerregionen (Default 200); erzwungene Regionen kommen hinzu |
| `--time-limit S` | Zeitlimit für HiGHS in Sekunden |
| `--pair-threshold KM` | maximale Distanz für zusätzliche Zweier-Routen im Pool |
| `--jitter N` | zusätzliche randomisierte Savings-Läufe für den Routenpool |
| `--initial FILE` | Warmstart aus einem früheren Ergebnis |
| `--out FILE` | Zielpfad der JSON-Ergebnisdatei |

### 640er-Referenzlauf (exakter Pool-Beweis)

```bash
.venv/bin/python run_proof.py
```

Das Skript löst die Relaxation mit stetigem `λ`, prüft die Ganzzahligkeit der
Optimallösung, extrahiert das Netz und schreibt `results/milp_640.json`
(Laufzeit rund 568 s).  Es ist der Referenzlauf; die 202er-Lösung bleibt als
Sensitivität erhalten.

### Robustheit

```bash
.venv/bin/python run_robustness.py --base results/milp_640.json --initial-dir results/archive_202 --time-limit 1200
```

Das Zeitlimit ist nötig, weil beide 640er-Szenarioläufe das Limit erreichen:
pessimistisch nach 1.236 s (Gap 7,34 %), optimistisch nach 1.285 s (Gap 3,82 %).
Mit `--initial-dir results/archive_202` wird, falls besser, die alte
202er-Szenariolösung als Warmstart verwendet.

Das Skript bewertet das bestehende Netz unter beiden Szenarien und baut für
jedes Szenario einen **szenariospezifischen Routenpool** auf (inkl. der durch
den geänderten Rohertrag neu positiven Märkte).  Das bestehende Netz wird als
Warmstart übergeben, damit die Reoptimierung nie schlechter als das bestehende
Netz startet.  Mit `--only pessimistisch` bzw. `--only optimistisch` lässt sich
ein Szenario einzeln rechnen; `--mip-gap` setzt die Abbruchtoleranz.  Optional
baut `--depot-search` die analytische Baseline auf den Szenariodaten neu und
testet deren Depot.  Ergebnisse: `results/robustness_*.json` und
`results/robustness_summary.json`.

| Szenario | Bestehend | Reoptimiert | Delta | Märkte | Satelliten | Status / Gap |
|---|---:|---:|---:|---:|---:|---|
| Pessimistisch | 1.463.574 EUR | 1.526.843 EUR | +63.269 EUR | 115 → 90 | 5 → 4 | `kTimeLimit`, 7,34 % |
| Optimistisch | 3.382.396 EUR | 3.382.396 EUR | 0 EUR | 115 → 115 | 5 → 5 | `kTimeLimit`, 3,82 % |

Unter dem pessimistischen Szenario sinkt der Gewinn des 640er-Netzes auf
1.463.574 EUR; die Reoptimierung findet mit 90 Märkten und 4 Satelliten
1.526.843 EUR.  Der alte 202er-Lauf zertifizierte denselben Wert mit Gap 0 für
seinen damaligen Pool; er liegt im Archiv `results/archive_202/`.

Unter dem optimistischen Szenario bleibt das 640er-Netz unverändert
(3.382.396 EUR).  Der Solver bestätigt es als beste gefundene Lösung, konnte
im Zeitlimit aber keinen Gap-0-Beweis schließen.  Die historische
109er-Gegenprobe zum alten 202er-Netz liegt in
`results/archive_202/crosscheck_optimistic_109/`.

### Tests

```bash
.venv/bin/python -m pytest -q
```

## 2. Modell

### Entscheidungen

* Depotregion `d` (genau eine) – **vorgelagert** per Enumeration aller 671
  Regionen in der Baseline; das MILP optimiert bei festem Depot,
* Satellitenregionen `S` (optional),
* geöffnete Märkte `I_open`,
* Zuordnung jedes geöffneten Marktes zu genau einem Lager,
* Wochenrouten je Lager (Reihenfolge der Märkte),
* Routenmultiplizität `0…v` pro Woche mit `v = 3`.

### Annahmen

* 52 identische Wochen pro Jahr.
* Jeder geöffnete Markt wird genau `v`-mal pro Woche beliefert (Datenwert:
  `v = 3`).
* Ein Markt wird pro Route höchstens einmal angefahren; die Routen dürfen
  sich zwischen den drei Wochenlieferungen unterscheiden.
* Eine Route ist eine Rundtour Lager → Märkte → Lager.  Fahrzeit
  (Distanz / 50 km/h) plus 30 min Servicezeit pro Markt darf 8 h nicht
  überschreiten.
* Lkw fahren genau einmal pro Woche vom Depot zu jedem Satelliten (Hin- und
  Rückfahrt).
* Fahrzeuganzahl, Kapazitäten und Bestände sind unbeschränkt.
* Ein Markt deckt den Rohertrag seiner Region vollständig ab.

### Zielfunktion

```text
Gewinn = Σ Rohertrag(geöffnete Märkte)
       − Σ Marktkosten
       − Depotkosten
       − Σ Satellitenkosten
       − Σ Lkw-Kosten (Depot ↔ Satellit)
       − Σ Transporterkosten (Routen)
```

### MILP

Das Optimierungsmodell ist ein Set-Partitioning-Modell mit Standort- und
Zuordnungsentscheidungen:

* `y_i ∈ {0,1}`: Markt `i` geöffnet,
* `z_w ∈ {0,1}`: Lager `w` geöffnet (Depot oder Satellit),
* `a_{i,w} ∈ {0,1}`: Markt `i` wird von Lager `w` bedient,
* `λ_r ∈ {0,…,v}`: Route `r` wird 0- bis `v`-mal pro Woche gefahren.

Nebenbedingungen:

```text
Σ_{r ∋ i} λ_r = v · y_i                für jeden Markt i
Σ_w a_{i,w} = y_i                      für jeden Markt i
Σ_{r ∋ i, r aus w} λ_r ≤ v · a_{i,w}   für jedes Paar (i,w)
Σ_{r aus w} λ_r ≤ M_w z_w              für jedes Lager w
```

Dabei ist `M_w = v · |{i : i kommt in einer Route von w vor}|` eine gültige
Obergrenze für die Fahrten von Lager `w`.

Die Route `r` enthält eine Menge von Märkten; ihre Kosten sind die Rundtour
vom Lager über diese Märkte zurück zum Lager (bis 13 Märkte exakt per
Held-Karp, darüber 2-opt-Heuristik), annualisiert mit 52 Wochen.  Der
Routenpool wird aus Savings-Routen, Singletons, kurzen Zweier-Routen und
optionalen Jitter-Varianten erzeugt.

## 3. Ergebnisse

| Lauf | Kandidaten | Routenpool | Märkte | Fahrten/Woche | Jahresgewinn | Gap | Laufzeit |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | alle 671 Depots | Savings | 120 | 60 | 2.312.477 EUR | – | 170 s |
| MILP 202 (Sensitivität) | 202 | 103.063 | 111 | 54 | 2.400.887 EUR | 0,00 % | 481 s |
| **MILP 640 (Referenz)** | **640** | **159.060** | **115** | **57** | **2.422.985 EUR** | **0,00 %** | **568 s** |

Der 640er-Lauf ist die Referenz: Er verbessert die Baseline um **110.508 EUR
(+4,78 %)** und den 202er-Lauf um **22.099 EUR (+0,92 %)**.  Er nutzt 640
nicht-dominierte Lagerregionen, 159.060 Routen, 115 Märkte und 57 Fahrten; die
Satelliten sind 84, 122, 271, 419 und 574.

Der 640er-Beweis wurde als Relaxation der Routenmultiplizitäten geführt:
Markt-, Lager- und Zuordnungsvariablen bleiben binär, `λ` wird stetig.  HiGHS
meldet `kOptimal`; die Optimallösung ist **ganzzahlig** und ergibt exakt
dieselbe Bewertung wie das extrahierte Netz.  Damit ist der 640er-Routenpool
exakt gelöst.  Der ganzzahlige 640er-MILP-Lauf selbst erreichte nach 1.827,6 s
nur `kTimeLimit` mit Gap 3,5685 %.

Die Robustheitsergebnisse stehen in `results/robustness_summary.json`; die
Einzelresultate liegen in `results/robustness_pessimistisch.json` und
`results/robustness_optimistisch.json`.  Das Skript `make_report.py` erzeugt daraus:

* `slides/gewinnbruecke.png`
* `slides/netzwerk.png`
* `slides/robustheit.png`
* die Präsentation `slides/Mini-Supermarkt-Netz.pptx`

## 4. Optimalität – was bewiesen ist und was nicht

Der 640er-Lauf liefert ein zertifiziertes Optimum für den **verwendeten
Routenpool** und **alle 671 Lagerregionen** bei festem Depot 379:

* 31 Regionen sind durch eine Lagerregion mit nicht höheren Fixkosten und
  nicht größeren Distanzen zu allen Märkten dominiert.  Für jede dominierte
  Region wurde eine Dominanzkette in die Pareto-Front verifiziert.
* Die verbleibenden **640 nicht-dominierten Regionen** sind daher
  kandidatenvollständig: Jede Lösung mit einer dominierten Region lässt sich
  ohne Verschlechterung in eine Lösung mit ihrem Dominator umwandeln.
* Die 202er-Menge des früheren Referenzlaufs ist **nicht**
  kandidatenvollständig; 443 nicht-dominierte Regionen fehlen dort.  Sie bleibt
  als Sensitivität dokumentiert.

**Nicht bewiesen ist ein globales Optimum über alle theoretisch möglichen
Routen und alle 671 Depots:**

* Der Routenpool enthält 159.060 heuristisch erzeugte Routen, nicht alle
  zulässigen Routen.  Eine vollständige Routenenumeration ist bei 150 Märkten
  und 8-Stunden-Routen nicht darstellbar.
* Das Depot 379 wird vorgelagert in der Baseline durch Enumeration aller 671
  Regionen bestimmt; das MILP optimiert bei diesem festen Depot.  Ein
  vollständiger Vergleich aller Depotalternativen mit exakten Schranken ist
  nicht geführt.
* Die LP-Relaxation des 202er-Modells liefert eine obere Schranke von
  3,156 Mio. EUR und ist damit zu schwach für einen Beweis.
* Ein vollständiger Beweis über alle Routen und Depots würde Branch-and-Price
  mit exaktem Pricing oder eine vollständige Routenenumeration erfordern.

### 4.1 Kandidatenvollständigkeit und 640er-Beweis

Die Details und Rohdaten des 640er-Beweises liegen in
`experiments/full_exact/`:

* `build_candidates.py` erzeugt die 640er-Pareto-Front und verifiziert alle
  Dominanzketten,
* `run_expanded.py` dokumentiert den ganzzahligen 640er-MILP-Lauf
  (`kTimeLimit`, Gap 3,5685 %),
* `run_relaxed_bound.py` löst die Relaxation mit stetigem `λ` und erzeugt die
  Solution-Datei,
* `extract_solution.py` extrahiert und validiert das ganzzahlige Netz,
* `results/milp_640.sol` und `results/milp_640_proof.log` dokumentieren den Beweislauf.

Ein exakter Pricing-Prototyp (`scm/pricing.py`) löst die getesteten Lager
149, 122, 575, 84, 419, 271 und 379 exakt (0,1–220,9 s).  Der Engpass ist die
Anzahl der Pricing-Aufrufe über 640 Lager und viele Branch-and-Price-Knoten.
Ein Probelauf mit sechs neuen Routen erhöhte die LP-Schranke von 3,3345 auf
3,3393 Mio. EUR; die verbleibende Lücke zum Integer-Optimum ist damit
Integralität der Standort-/Zuordnungsentscheidungen, nicht der Routenpool.

Die Baseline-Enumeration führt Depot 379 nur mit **2.512 EUR Vorsprung**
vor Depot 351 (722.019 vs. 719.507 EUR); die Depotwahl ist damit nicht
bewiesen.  Ein 640er-Relaxationslauf für Depot 375 ergibt 2.422.478,98 EUR
(`kOptimal`, 754,0 s, ganzzahlig) und liegt damit nur **506,12 EUR** unter
379.  Depot 351 liegt 2.582,37 EUR, Depot 349 8.296,20 EUR und Depot 350
14.884,56 EUR unter 379.  Das stützt 379, ist aber kein Beweis über alle 671
Depots.  Eine räumliche Top-5-Reduktion (316 Kandidaten, 93.092 Routen) ist 21.955 EUR
schlechter als die Referenz, weil sie die entscheidenden Satelliten 84 und 574
ausschließt.  Mit erzwungenen Referenzsatelliten (318 Kandidaten) bleibt das
Optimum erhalten und der Beweis dauert nur 305,5 s.  Räumliche Nähe ist also
ein Speed-up, kein Beweis.

Für die **optimale Zuordnung** wurde das Routing über alle Routen bewiesen:
Der feste Zuordnungsmaster hat 936.596,31 EUR Transporterkosten, keine Route
mit positivem reduziertem Preis und eine ganzzahlige Optimallösung
(`fixed_network_bp.log`).  Offen bleibt der Beweis für andere Zuordnungen und
alle 671 Depots.

## 5. Projektstruktur

```text
scm/
  data.py          Daten laden und validieren
  network.py       Netzwerk, Profitbewertung, Validierung
  routing.py       Savings, 2-opt, Held-Karp, Routenfeasibility
  baseline.py      Analytische Baseline + lokale Verbesserung
  routes_pool.py   Routenpool für das MILP
  milp.py          Set-Partitioning-MILP mit HiGHS
  pricing.py       Exaktes Pricing (Branch-and-Price-Prototyp)
  scenarios.py     Robustheitsszenarien und Repricing
  analysis.py      Gewinnbrücke, Netzkarte, Szenariovergleich
  io.py            JSON-Serialisierung
run_baseline.py    Baseline ausführen
run_milp.py        MILP ausführen
run_proof.py       640er-Pool-Beweis reproduzieren
run_robustness.py  Szenarien bewerten und reoptimieren
make_report.py     Abbildungen und Präsentation erzeugen
tests/             Pytest-Tests
results/           JSON-Ergebnisse und Provenienz (results/README.md)
slides/            Abbildungen und PPTX
experiments/       Kandidatenvollständigkeit und 640er-Beweis
```

## 6. Reproduzierbarkeit

Alle Zufallskomponenten (Jitter) verwenden einen festen Seed.  HiGHS läuft mit
fester Thread-Zahl und Zeitlimit.  Die Ergebnisse können je nach
HiGHS-Version und Thread-Anzahl minimal variieren; die JSON-Dateien enthalten
Status, Gap und Laufzeit.
