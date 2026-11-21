package tech.enlightenedrepublic.caelza.voice

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The dashboard's way to the phone's voices (vision M10 §10, slice P2b).
 * Android's WebView has no `speechSynthesis`, so the page calls
 * `window.caelzaVoice` instead: [voices] is the phone's text-to-speech voices
 * as the offer the gateway takes, [speak] reads a reply in the chosen one, and
 * the page hears `caelza-voice` events (start, done, error) to move the
 * character's mouth. Only the gateway's own pages load in this WebView
 * (MainActivity.TokenHandoff), so nothing else can reach the bridge.
 */
class VoiceBridge(context: Context, private val webView: WebView) {
    private val main = Handler(Looper.getMainLooper())
    private val appContext = context.applicationContext
    /** Made on the main thread, read from the WebView's bridge thread. */
    @Volatile
    private var tts: TextToSpeech? = null
    private val ready = AtomicBoolean(false)

    init {
        main.post {
            tts = TextToSpeech(appContext) { status -> ready.set(status == TextToSpeech.SUCCESS) }
        }
    }

    private fun phoneVoices(): List<PhoneVoice> {
        val engine = tts ?: return emptyList()
        if (!ready.get()) return emptyList()
        val raw = try {
            engine.voices
        } catch (e: Exception) {
            Log.w(TAG, "the engine would not list its voices", e)
            null
        } ?: return emptyList()
        return raw.filter { !it.name.isNullOrBlank() }
            .map { PhoneVoice(it.name, it.locale.toLanguageTag(), it.quality, it.isNetworkConnectionRequired) }
    }

    /** The phone's voices as JSON (`[{id, name, lang}]`); `[]` until the engine is ready. */
    @JavascriptInterface
    fun voices(): String = VoiceCatalog.json(phoneVoices())

    /**
     * Speak [text] in the voice named [voice] (blank: the engine's default) at
     * [rate] and [pitch] (1 is as it comes). False when the engine is not ready.
     */
    @JavascriptInterface
    fun speak(text: String, voice: String, rate: Float, pitch: Float): Boolean {
        if (!ready.get() || text.isBlank()) return false
        main.post {
            val engine = tts ?: return@post
            val chosen = VoiceCatalog.pick(phoneVoices(), voice)
            if (chosen != null) {
                try {
                    engine.voices?.firstOrNull { it.name == chosen.name }?.let { engine.voice = it }
                } catch (e: Exception) {
                    Log.w(TAG, "the engine would not take the voice", e)
                }
            }
            engine.setSpeechRate(rate.coerceIn(0.5f, 2f))
            engine.setPitch(pitch.coerceIn(0.5f, 2f))
            val id = "caelza-voice-${System.nanoTime()}"
            engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) {
                    tell("start", utteranceId)
                }

                override fun onDone(utteranceId: String?) {
                    tell("done", utteranceId)
                }

                @Suppress("OVERRIDE_DEPRECATION") // abstract in the base class, so it must be overridden even though deprecated
                override fun onError(utteranceId: String?) {
                    tell("error", utteranceId)
                }

                override fun onError(utteranceId: String?, errorCode: Int) {
                    tell("error", utteranceId)
                }
            })
            if (engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS) tell("error", id)
        }
        return true
    }

    @JavascriptInterface
    fun stop() {
        main.post { tts?.stop() }
    }

    fun shutdown() {
        main.post {
            tts?.shutdown()
            tts = null
            ready.set(false)
        }
    }

    private fun tell(state: String, id: String?) {
        val safeId = (id ?: "").filter { it.isLetterOrDigit() || it == '-' }
        val js = "window.dispatchEvent(new CustomEvent('caelza-voice', {detail: {state: '$state', id: '$safeId'}}))"
        main.post { webView.evaluateJavascript(js, null) }
    }

    companion object {
        private const val TAG = "VoiceBridge"
        /** The name the page finds it under: `window.caelzaVoice`. */
        const val JS_NAME = "caelzaVoice"
    }
}
