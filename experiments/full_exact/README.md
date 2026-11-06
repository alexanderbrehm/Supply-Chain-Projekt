# Kandidatenvollständigkeit und 640er-Beweis

Dieser Ordner dokumentiert, wie der Suchraum des früheren Referenzlaufs
`results/milp_200.json` erweitert und ein **stärkerer, zertifizierter
Optimalitätsbeweis** für das 640er-Modell geführt wurde.  Die neue Referenz
ist `results/milp_640.json`.

## 1. Kandidatenvollständigkeit

Für ein festes Depot 379 wird eine Lagerregion `w` von `w'` dominiert, wenn

* `satellite_cost(w') + truck_cost(379, w') <= satellite_cost(w) + truck_cost(379, w)`
  und
* `d(w', i) <= d(w, i)` für jeden potenziellen Markt `i`.

Dann kann jede Route von `w` mit derselben Marktfolge von `w'` gefahren werden,
ohne dass die Distanz oder die Fixkosten steigen.  Ersetzt man ein eröffnetes
dominiertes Lager durch seinen Dominator, wird die Lösung also nicht
schlechter.  Die Pareto-Front dieser Relation ist daher
**kandidatenvollständig**.

Ergebnis von `build_candidates.py`:

* 671 Regionen,
* 31 dominierte Regionen,
* **640 nicht-dominierte Regionen**,
* für jede dominierte Region wurde eine Dominanzkette in die Frontier geprüft.

Die 202er-Menge des früheren Referenzlaufs ist dagegen **nicht**
kandidatenvollständig: 443 nicht-dominierte Regionen fehlen dort.

## 2. Ganzzahliger 640er-MILP-Lauf

`run_expanded.py` löst das MILP mit allen 640 nicht-dominierten Kandidaten,
weiterhin mit festem Depot 379 und dem Savings-Routenpool:

* Routenpool: 159.060 Routen (15,3 s Erzeugung),
* Warmstart: `results/milp_200.json`,
* Zeitlimit: 1.800 s,
* Modell: 18.364 Zeilen, 177.274 Variablen (159.060 Routen, 17.424 Zuordnungen).

Ergebnis (`milp_640_integer_timeout.json`, `milp_640_integer_timeout.log`):

* Gewinn: **2.400.886,572 EUR** – dieselbe Lösung wie im 202er-Lauf,
* Status: `kTimeLimit`, MIP-Gap **3,5685 %** nach 1.827,6 s,
* 111 Märkte, dieselben fünf Satelliten, 54 Fahrten.

Der ganzzahlige Lauf findet also keine bessere Lösung, beweist aber auch nicht,
dass keine existiert.

## 3. Relaxationsbeweis mit ganzzahliger Optimallösung

`run_relaxed_bound.py` löst dasselbe Modell mit **stetigen
Routenmultiplizitäten** (`λ`), während Markt-, Lager- und
Zuordnungsentscheidungen binär bleiben.  Das ist eine Relaxation des
ganzzahligen Modells; ihr Optimalwert ist eine obere Schranke.

Ergebnis (`relaxed_bound_640_sol.json`, `relaxed_bound_640_sol.log`):

* Optimalwert: **2.422.985,098 EUR**,
* Status: `kOptimal`, Gap **0,00 %** nach 567,7 s,
* Routenpool: 159.060, 177.274 Variablen,
* die Optimallösung ist **in allen 177.274 Spalten ganzzahlig**.

`extract_solution.py` baut daraus das Netz, validiert es mit
`scm.network.evaluate` und bestätigt exakt denselben Gewinn.  Damit ist der
Wert **2.422.985,098 EUR** das exakte Optimum des 640er-Modells (feste
Depotregion 379, 159.060 Routen) und **22.098,526 EUR besser** als der
202er-Lauf.

## 4. Phase 1: exaktes Pricing (Prototyp)

`scm/pricing.py` implementiert drei exakte Pricing-Ansätze:

* `solve_pricing` – MIP mit MTZ-Subtour-Ausschluss,
* `solve_pricing_dfj` – MIP mit iterativen DFJ-Cuts,
* `solve_pricing_dfs` – Branch-and-Bound-DFS mit Dualpreis-Schranke.

Alle berücksichtigen nur Lagermärkte mit negativem Dualpreis; ein Markt mit
nicht-negativem Preis kann eine Route nicht verbessern, weil das Hinzufügen
eines Knotens in einer metrischen Tour die Distanz nicht verkürzt.

Ergebnis mit den Dualwerten der 640er-Master-LP (beste Methode je Lager):

| Lager | erreichbare Märkte | Methode | Status | Laufzeit | reduzierter Preis |
|---|---:|---|---|---:|---:|
| 149 | 7 | MTZ-MIP | `kOptimal` | 0,2 s | −4.655,49 |
| 122 | 12 | MTZ-MIP | `kOptimal` | 1,4 s | +2.325,76 |
| 575 | 24 | MTZ-MIP | `kOptimal` | 10,5 s | +11.348,45 |
| 84 | 31 | DFS | `kOptimal` | 220,9 s | +10.374,40 |
| 419 | 34 | DFS | `kOptimal` | 50,8 s | +13.287,27 |
| 271 | 41 | SCIP-MIP | `kOptimal` | 160,9 s | +11.494,95 |
| 379 | 60 | DFS | `kOptimal` | 37,6 s | +2.526,84 |

Für die getesteten Lager funktioniert exaktes Pricing mit einem Hybrid aus
MTZ-MIP, SCIP und DFS.  Der Engpass ist die **Anzahl** der Pricing-Aufrufe:
640 Lager pro Iteration und viele Branch-and-Price-Knoten sind damit nicht in
30 Minuten erreichbar.

## 5. Größerer Jitter-Pool

Ein Lauf mit `jitter_runs=10` erzeugt 178.097 Routen.  Mit dem 640er-Netz als
Warmstart erreicht er nach 1.828,7 s nur `kTimeLimit` mit Gap 12,68 %; die
beste gefundene Lösung bleibt **2.422.985,098 EUR**.  Der größere Pool liefert
also keine Verbesserung, aber auch keinen Beweis.

## 6. Spaltengenerierung: warum sie den Integer-Beweis nicht schließt

Ein Probelauf hat die sechs besten neuen Routen (122, 575, 84, 419, 271, 379)
zum Pool hinzugefügt und die LP erneut gelöst:

* Pool: 159.060 → 159.066 Routen,
* LP-Schranke: 3.334.545,70 → **3.339.301,29 EUR**.

Die LP-Schranke **steigt** durch neue Spalten (bei Maximierung ist das
erwartbar); sie liegt weiterhin rund 0,92 Mio. EUR über dem ganzzahligen
Optimum 2.422.985,10 EUR.  Die verbleibende Lücke ist damit **Integralität der
Standort-/Zuordnungsentscheidungen**, nicht ein fehlender Routenpool.  Ein
vollständiger Beweis bräuchte Branch-and-Cut mit starken
Standort-/Routing-Cuts – nicht nur Column Generation.

## 7. Fixierte Zuordnung: Routenbeweis über alle Routen

`fixed_network_bp.py` löst für die optimale Zuordnung des 640er-Netzes ein
kleines Set-Partitioning-Masterproblem mit exaktem Pricing:

* offene Lager: 379, 84, 122, 271, 419, 574,
* 115 Märkte mit fester Zuordnung,
* Startpool: 1.219 Routen,
* Master-LP: 936.596,31 EUR – exakt die aktuellen Transporterkosten,
* Pricing aller sechs Lager: **keine Route mit positivem reduziertem Preis**,
* die Optimallösung ist ganzzahlig (`fractional lambda = 0`).

Damit ist das **Routing der optimalen Zuordnung über alle zulässigen Routen**
bewiesen, nicht nur über den 159.060er-Pool.  Ergebnisse:
`fixed_network_bp.json`, `fixed_network_bp.log`.

## 8. Fixiertes Sechs-Lager-Modell: Integralitätslücke

`fixed_open_bp.py` lockert zusätzlich die Zuordnung und erlaubt der LP, Märkte
und Zuordnungen frei zu wählen.  Die LP-Schranke liegt bei **3.442.740,69 EUR**
und damit nochmals über der 640er-LP.  Neue Routen mit positivem reduziertem
Preis erhöhen die LP-Schranke (Maximierung) und schließen die Lücke zum
Integer-Optimum 2.422.985,10 EUR nicht.  Die verbleibende Lücke ist
**Integralität der Standort-/Zuordnungsentscheidungen**, nicht der Routenpool.

## 9. Depotvergleich: 379 führt nur knapp

Die Baseline-Enumeration (Savings-Routing, alle erreichbaren Märkte) liefert
folgende erste Plätze:

| Rang | Depot | Profit |
|---:|---:|---:|
| 1 | 379 | 722.019 EUR |
| 2 | 351 | 719.507 EUR |
| 3 | 375 | 715.664 EUR |
| 4 | 349 | 699.652 EUR |
| 5 | 350 | 690.856 EUR |

Für die ersten vier Depots wurde das 640er-Relaxationsmodell gelöst:

| Depot | Profit | Delta zu 379 | Status | Laufzeit |
|---:|---:|---:|---|---:|
| **379** | **2.422.985,10 EUR** | 0 | `kOptimal` | 567,7 s |
| 375 | 2.422.478,98 EUR | −506,12 EUR | `kOptimal` | 754,0 s |
| 351 | 2.420.402,73 EUR | −2.582,37 EUR | `kOptimal` | 618,3 s |
| 349 | 2.414.688,90 EUR | −8.296,20 EUR | `kOptimal` | 903,7 s |
| 350 | 2.408.100,53 EUR | −14.884,56 EUR | `kOptimal` | 706,3 s |

Alle Lösungen sind ganzzahlig.  **379 führt damit nur mit 506,12 EUR vor
375.**  Die ersten fünf Baseline-Depots sind damit verglichen, aber nicht alle
671.  Die Depotwahl ist durch die Baseline-Enumeration nicht bewiesen; ein
vollständiger Globalbeweis muss alle 671 Depots mit gültigen Schranken
vergleichen.  Details: `depot_comparison.json`, `depot_375_long.json`,
`depot_351.json`, `depot_349.json`, `depot_baseline_ranking.json`.

## 10. Räumliche Kandidatenreduktion (Top-5 nächste Depots)

`spatial_candidates.py` behält für jeden Markt nur die fünf nächsten
Depotregionen.  Ergebnis:

| Variante | Kandidaten | Routen | Profit | Status | Laufzeit |
|---|---:|---:|---:|---|---:|
| **Top-5 ohne Zwang** | 316 | 93.092 | 2.401.030,14 EUR | `kOptimal` | 477,2 s |
| **Top-5 + Referenzlager** | 318 | 93.554 | **2.422.985,10 EUR** | `kOptimal` | **305,5 s** |

Die reine Top-5-Reduktion ist **21.954,96 EUR schlechter** als die Referenz:
Sie schließt die für das Optimum entscheidenden Satelliten **84 und 574** aus.
Erzwingt man die fünf Referenzsatelliten zusätzlich, bleibt das Optimum
erhalten und der Beweis wird von 567,7 s auf **305,5 s** beschleunigt.

Damit ist die räumliche Reduktion ein nützlicher **Speed-up**, aber allein
**kein gültiger Beweis**: „räumlich nah“ heißt nicht „optimal“.  Dateien:
`spatial_k5.json`, `spatial_k5.log`, `spatial_k5_noforce.json`,
`spatial_k5_noforce.log`.

## 11. Gültige technische Ausschlüsse (keine Heuristik)

`technical_pruning.py` nutzt beweisbare Schranken, keine Vermutungen:

* **Lager w:** Wenn selbst die Summe aller erreichbaren Marktmargen kleiner ist
  als Satellitenfixkosten + Lkw-Kosten + minimal mögliche Transportkosten für
  einen Markt, kann `w` niemals profitabel sein.
* **Depot d:** Analog mit Depotkosten + minimal möglichen Transportkosten.

Ergebnis für Depot 379:

| Ebene | Start | gültig ausgeschlossen | verbleibend |
|---|---:|---:|---:|
| Lagerkandidaten | 640 | **23** | **617** |
| Depotkandidaten | 671 | **149** | **522** |

Die ausgeschlossenen Kandidaten können in **keiner** zulässigen Lösung
profitabel sein.  Das ist eine echte Reduktion, keine Heuristik.  Es bleiben
aber 617 Lager und 522 Depots – der Beweis über alle Routen/Zuordnungen ist
damit nicht erledigt.  Dateien: `technical_pruning.json`,
`candidates_617.json`.

## 12. Grenzen

* Der Beweis ist exakt bezüglich des erzeugten Routenpools, aber nicht
  bezüglich **aller theoretisch möglichen Routen**.
* Eine vollständige Routenenumeration ist bei 150 Märkten und 8-Stunden-Routen
  nicht darstellbar.  Schon für einzelne zentrale Lager wurden in 30 s über
  700.000 MST-zulässige Teilmengen explorisiert, ohne die Enumeration zu
  beenden.
* Ein vollständiger Beweis über alle 671 Depots würde zusätzlich einen
  exakten Vergleich aller Depotalternativen erfordern.  Die Baseline-
  Enumeration liefert dafür nur heuristische untere Schranken, keine
  zertifizierten oberen Schranken.
* Die LP-Relaxation des 202er-Modells liefert eine obere Schranke von
  3,156 Mio. EUR und ist damit zu schwach für einen Beweis
  (`lp_bound_202.json`).

## Fazit

Die Kandidatenrestriktion ist beweisbar entfernt; für den 159.060-Routen-Pool
ist das Optimum exakt bewiesen.  Ein vollständiger globaler Beweis über alle
Routen und alle 671 Depots bleibt offen.
