// The agent's reports end with Temuan → Bukti → Batasan → Langkah berikutnya.
// The chat shows the findings as the answer and folds the rest (evidence,
// limitations, next step) into a compact "Bukti" section the user can open.

final _evidenceHead = RegExp(r'^[ \t]*(?:#{1,4}[ \t]*|\*\*)?(?:bukti|evidence)\b[^\n]*$', caseSensitive: false, multiLine: true);

/// Split a finished answer at its "Bukti"/"Evidence" heading. `evidence` is
/// null when there is no such heading or nothing comes before it.
({String main, String? evidence}) splitEvidence(String text) {
  final m = _evidenceHead.firstMatch(text);
  if (m == null) return (main: text, evidence: null);
  final main = text.substring(0, m.start).trimRight();
  final rest = text.substring(m.end).trim();
  if (main.isEmpty || rest.isEmpty) return (main: text, evidence: null);
  return (main: main, evidence: rest);
}
