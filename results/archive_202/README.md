# Archiv: 202er-Referenz und alte Robustheit

Dieser Ordner enthält die frühere, überholte 202-Kandidaten-Referenz:

* `robustness_*.json/.log` – Szenarioläufe für das alte 202er-Netz,
  pessimistisch mit `kOptimal`/Gap 0, optimistisch mit Gap 1,26 %.
* `crosscheck_optimistic_109/` – Gegenprobe zum alten 202er-Netz mit 109
  Kandidaten; exakt dieselbe Lösung, Gap 0,48 % innerhalb der 0,5-%-Toleranz.

Die aktuelle Referenz ist `../milp_640.json` mit 640 nicht-dominierten
Lagerkandidaten und dem 159.060-Routen-Pool.  Die alten Szenariowerte sind
nicht mehr unmittelbar mit dem 640er-Netz vergleichbar.
