// "Hey Neo" matcher, the same rules as WakePhrase.kt (the service decides;
// this copy labels what "Tes Hey Neo" heard). The English Vosk model has no
// word "neo", so it hears in-vocabulary sound-alikes ("knee oh", "neil",
// "neon"); those count as the name.
const wakeGreetings = ['hey', 'hei', 'hay', 'hi', 'hai', 'halo', 'hallo', 'hello', 'okay', 'ok'];
const wakeNames = ['neo', 'knee oh', 'knee o', 'neil', 'neal', 'kneel', 'neon', 'nio', 'nia'];

String normalizeWakeText(String? text) =>
    (text ?? '').toLowerCase().replaceAll(RegExp(r'[^a-z ]'), ' ').replaceAll(RegExp(r'\s+'), ' ').trim();

bool matchesWakePhrase(String? text) {
  final t = normalizeWakeText(text);
  if (t.isEmpty) return false;
  for (final n in wakeNames) {
    if (t == n) return true;
    for (final g in wakeGreetings) {
      if (RegExp('\\b$g $n\\b').hasMatch(t)) return true;
    }
  }
  return false;
}
