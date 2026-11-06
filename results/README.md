# Ergebnisdateien – Provenienz

Alle Werte sind Jahreswerte in EUR.  Die JSON-Dateien enthalten Netz,
Gewinnaufschlüsselung sowie Solver-Status, MIP-Gap und Laufzeit.  Die
**Referenzlösung ist `milp_640.json`**.

| Datei | Inhalt | Wesentliche Kennzahlen |
|---|---|---|
| `baseline.json` | Baseline-Netz und -Bewertung | 2.312.476,868 EUR; Depot 379; 120 Märkte; 60 Fahrten/Woche; 170,0 s |
| `milp_104.json` | MILP mit 108 Lagerkandidaten (Sensitivität) | 2.348.584,150 EUR; 112 Märkte; 57 Fahrten; Pool 66.758; `kOptimal`, Gap 0; 170,0 s |
| `milp_200.json` | MILP mit 202 Lagerkandidaten (Sensitivität) | 2.400.886,572 EUR; 111 Märkte; 54 Fahrten; Pool 103.063; `kOptimal`, Gap 0; 480,7 s |
| **`milp_640.json`** | **Referenz: 640 nicht-dominierte Lagerkandidaten** | **2.422.985,098 EUR**; 115 Märkte, 57 Fahrten; Pool 159.060; `kOptimal`, Gap 0; 567,7 s; Satelliten 84, 122, 271, 419, 574 |
| `candidates_640.json` | Pareto-Front der Lagerkandidaten | 640 nicht-dominierte Regionen; 31 dominiert, Dominanzketten geprüft |
| `milp_640.sol` | HiGHS-Solution-Datei des Beweislaufs | 177.274 Spalten; Optimallösung ganzzahlig |
| `milp_640_proof.log` | HiGHS-Log des Beweislaufs | `kOptimal`, Gap 0, 567,7 s |
| `robustness_pessimistisch.json` | Pessimistisch: Rohertrag −10 %, km-Kosten +10 % | bestehend 1.463.574,408 EUR → reoptimiert **1.526.843,175 EUR**; 90 Märkte, 4 Satelliten; `kTimeLimit`, Gap 7,34 %; 1.236,4 s |
| `robustness_optimistisch.json` | Optimistisch: Rohertrag +10 %, km-Kosten −10 % | bestehend 3.382.395,788 EUR → reoptimiert **3.382.395,788 EUR** (Netz unverändert); 115 Märkte, 5 Satelliten; `kTimeLimit`, Gap 3,82 %; 1.285,3 s |
| `robustness_summary.json` | kompakte Zusammenfassung beider Szenarien | Pessimistisch +63.268,767 EUR; Optimistisch 0 EUR |
| `archive_202/` | Robustheit des alten 202er-Netzes | alte, gap-0-zertifizierte Szenariorechnung; nicht mehr Referenz |
| `archive_202/crosscheck_optimistic_109/` | Gegenprobe zum alten 202er-Netz | 109 Kandidaten, gleiche Lösung, Gap 0,48 %; historisch |

## Logs

* `baseline.log` – vollständiger Baseline-Lauf.
* `milp_200.log` – HiGHS-/Ergebnislog des 202er-Sensitivitätslaufs.
* `milp_300_partial.log` – **Auszug** des 300er-Sensitivitätslaufs
  (Warmstart aus dem 202er-Netz, Abbruch nach 615,8 s bei Gap 2,32 %, keine
  bessere Lösung).  Der Lauf ist kein Optimalitätsnachweis.
* `milp_640_proof.log` – vollständiger Beweislauf des 640er-Modells.
* `robustness_640_pessimistisch.log` – pessimistischer 640er-Szenariolauf.
* `robustness_640_optimistisch.log` – optimistischer 640er-Szenariolauf.
* `archive_202/robustness_*.log` – alte 202er-Szenarioläufe.

## Hinweise

* Der 640er-Lauf ist optimal für den erzeugten Routenpool und **alle 671
  Lagerregionen** bei festem Depot 379.  Die 31 dominierten Regionen sind
  beweisbar ersetzbar; die 640 nicht-dominierten Regionen sind
  kandidatenvollständig.  Ein globaler Beweis über **alle theoretisch
  möglichen Routen** und **alle 671 Depots** ist nicht erbracht; siehe
  Abschnitt 4 der Haupt-README.
* Der 202er-Lauf ist **nicht** kandidatenvollständig: 443 nicht-dominierte
  Regionen fehlen dort.  Er bleibt als Sensitivität erhalten.
* Der 640er-Beweis nutzt eine Relaxation der Routenmultiplizitäten (`λ`
  stetig, Markt-/Lager-/Zuordnungsvariablen binär).  Die Optimallösung ist
  ganzzahlig; damit ist sie auch für das ganzzahlige Modell optimal.  Der
  ganzzahlige 640er-MILP-Lauf selbst erreichte nach 1.827,6 s nur
  `kTimeLimit` mit Gap 3,5685 % (`experiments/full_exact/milp_640_integer_timeout.log`).
* Die JSON-Werte sind die maschinenlesbare Quelle; gerundete Angaben in
  README und Präsentation können deshalb minimal abweichen.
* `archive_202/robustness_summary.json` enthält den `cross_check`-Block der
  alten 109er-Gegenprobe.  Die aktuelle 640er-Zusammenfassung wird von
  `run_robustness.py` ohne diesen Block geschrieben.
