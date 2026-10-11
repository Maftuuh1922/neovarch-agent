package com.neovarch.agent

/**
 * "Hey Neo" grammar + tolerant matcher (pure Kotlin, unit-tested; the Dart
 * copy in lib/remote/wake_phrase.dart follows the same rules for the
 * "Tes Hey Neo" readout).
 *
 * The small English Vosk model has no word "neo" in its vocabulary, so a
 * grammar of "hey neo" silently lost "neo" and never matched. The grammar
 * therefore uses in-vocabulary sound-alikes ("knee oh", "neil", "neon", …)
 * and the matcher maps them back.
 */
object WakePhrase {
    val GREETINGS = listOf("hey", "hei", "hay", "hi", "hai", "halo", "hallo", "hello", "okay", "ok")
    /** How "Neo" comes out of an English recogniser. */
    val NAMES = listOf("neo", "knee oh", "knee o", "neil", "neal", "kneel", "neon", "nio", "nia")

    /** Vosk grammar: greeting + name, the bare name, and [unk] for everything else. */
    val GRAMMAR: String = buildList {
        for (g in listOf("hey", "hi", "hello", "halo", "okay")) for (n in listOf("knee oh", "neil", "neon", "kneel")) add("$g $n")
        addAll(listOf("knee oh", "neil", "neon", "[unk]"))
    }.joinToString(prefix = "[", postfix = "]") { "\"$it\"" }

    fun normalize(text: String?): String =
        (text ?: "").lowercase().replace(Regex("[^a-z ]"), " ").replace(Regex("\\s+"), " ").trim()

    fun matches(text: String?): Boolean {
        val t = normalize(text)
        if (t.isEmpty()) return false
        for (n in NAMES) {
            if (t == n) return true // just "Neo"
            for (g in GREETINGS) if (Regex("\\b$g $n\\b").containsMatchIn(t)) return true
        }
        return false
    }
}
