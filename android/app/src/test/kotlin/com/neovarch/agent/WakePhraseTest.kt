package com.neovarch.agent

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WakePhraseTest {
    @Test fun matchesGreetingPlusName() {
        for (t in listOf("hey neo", "Hey Neo!", "halo neo", "hello knee oh", "hey neil", "hi neon", "okay kneel", "so hey neil please")) {
            assertTrue(t, WakePhrase.matches(t))
        }
    }

    @Test fun matchesBareName() {
        assertTrue(WakePhrase.matches("neo"))
        assertTrue(WakePhrase.matches("knee oh"))
    }

    @Test fun ignoresOtherSpeech() {
        for (t in listOf("", "[unk]", "hey", "hello there", "neon lights are bright", "honey oh", "money")) {
            assertFalse(t, WakePhrase.matches(t))
        }
    }

    @Test fun grammarHasUnknownAndNoOutOfVocabularyNeo() {
        assertTrue(WakePhrase.GRAMMAR.contains("\"[unk]\""))
        assertFalse(WakePhrase.GRAMMAR.contains("neo\""))
    }
}
