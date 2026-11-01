package tech.enlightenedrepublic.caelza.logs

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import com.google.android.material.chip.Chip
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import tech.enlightenedrepublic.caelza.BuildConfig
import tech.enlightenedrepublic.caelza.R
import tech.enlightenedrepublic.caelza.RuntimeService
import tech.enlightenedrepublic.caelza.databinding.ActivityLogsBinding
import tech.enlightenedrepublic.caelza.runtime.RuntimeStore
import tech.enlightenedrepublic.caelza.shizuku.ShizukuStatus
import java.io.File

/**
 * The logs, on the phone (design §2 "Logs"): one chip per source (BugReport.sources), the
 * end of the chosen file in monospace with secrets blanked, Refresh, and Share, which
 * writes the bug report (BugReport.render) under the cache dir and offers it through the
 * share sheet as a text file (FileProvider, `<applicationId>.files`). Nothing leaves the
 * phone unless the owner picks where it goes.
 */
class LogsActivity : AppCompatActivity() {
    private lateinit var b: ActivityLogsBinding
    private lateinit var store: RuntimeStore
    private lateinit var sources: List<BugReport.Source>
    private val chips = mutableMapOf<Int, BugReport.Source>()
    private var current: BugReport.Source? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityLogsBinding.inflate(layoutInflater)
        setContentView(b.root)
        store = RuntimeStore(filesDir)
        sources = BugReport.sources(store, filesDir)
        for (source in sources) {
            val chip = layoutInflater.inflate(R.layout.chip_source, b.sourceChips, false) as Chip
            chip.id = View.generateViewId()
            chip.text = source.label
            chips[chip.id] = source
            b.sourceChips.addView(chip)
        }
        b.sourceChips.setOnCheckedStateChangeListener { _, checked ->
            checked.firstOrNull()?.let { chips[it] }?.let { show(it) }
        }
        b.refreshButton.setOnClickListener { current?.let { show(it) } }
        b.shareButton.setOnClickListener { share() }
        b.backButton.setOnClickListener { finish() }
        val wanted = BugReport.byId(sources, savedInstanceState?.getString(EXTRA_SOURCE) ?: intent.getStringExtra(EXTRA_SOURCE))
        chips.entries.firstOrNull { it.value.id == wanted.id }?.let { b.sourceChips.check(it.key) }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        current?.let { outState.putString(EXTRA_SOURCE, it.id) }
    }

    override fun onResume() {
        super.onResume()
        current?.let { show(it) }
    }

    private fun show(source: BugReport.Source) {
        current = source
        b.about.text = source.about
        lifecycleScope.launch {
            val (text, footer) = withContext(Dispatchers.IO) {
                val file = source.file
                if (!file.isFile) {
                    getString(R.string.logs_empty, source.label) to "${file.path} · ${BugReport.MISSING}"
                } else {
                    BugReport.scrub(BugReport.tail(file)) to getString(R.string.logs_footer, file.path, BugReport.human(file.length()))
                }
            }
            if (current !== source) return@launch
            b.logText.text = text
            b.footer.text = footer
            b.logScroll.post { b.logScroll.fullScroll(View.FOCUS_DOWN) }
        }
    }

    /** The report into `cache/bugreport/`, older ones dropped, then the share sheet with it attached. */
    private fun share() {
        b.shareButton.isEnabled = false
        lifecycleScope.launch {
            val file = withContext(Dispatchers.IO) {
                val dir = File(cacheDir, BugReport.REPORT_DIR).apply { mkdirs() }
                dir.listFiles()?.forEach { it.delete() }
                File(dir, BugReport.fileName()).also { it.writeText(BugReport.render(header(), sources)) }
            }
            val uri = FileProvider.getUriForFile(this@LogsActivity, "${BuildConfig.APPLICATION_ID}.files", file)
            val send = Intent(Intent.ACTION_SEND)
                .setType("text/plain")
                .putExtra(Intent.EXTRA_SUBJECT, getString(R.string.logs_report_subject))
                .putExtra(Intent.EXTRA_TEXT, getString(R.string.logs_report_text))
                .putExtra(Intent.EXTRA_STREAM, uri)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            startActivity(Intent.createChooser(send, getString(R.string.logs_share)))
            b.shareButton.isEnabled = true
        }
    }

    /** What the report says about this phone before the logs: versions, device, states, room. */
    private fun header(): List<Pair<String, String>> {
        val state = RuntimeService.state.value
        val body = RuntimeService.body.value
        val model = RuntimeService.model.value
        val memory = ActivityManager.MemoryInfo().also { (getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(it) }
        return listOf(
            "app" to "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE}, ${BuildConfig.BUILD_TYPE}, build ${BuildConfig.BUILD_ID})",
            "device" to "${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT}), ${Build.SUPPORTED_ABIS.joinToString(",")}",
            "runtime" to "current ${store.current ?: "none"}, last-good ${store.lastGood ?: "none"}, installed ${store.installed().joinToString(", ").ifEmpty { "nothing" }}",
            "runtime state" to "${state.phase} ${state.version ?: ""} ${state.detail}".trim(),
            "body" to if (body.serving) "${body.tools} tools on :${body.port}" else "not serving ${body.detail}".trim(),
            "model" to if (model.configured) "${model.model}: ${model.detail}" else "none configured",
            "shizuku" to ShizukuStatus.label(ShizukuStatus.state()),
            "storage" to "${BugReport.human(filesDir.usableSpace)} free of ${BugReport.human(filesDir.totalSpace)} where the app lives",
            "memory" to "${BugReport.human(memory.availMem)} available of ${BugReport.human(memory.totalMem)}${if (memory.lowMemory) ", low" else ""}",
        )
    }

    companion object {
        /** A BugReport.Source id to open on; daemon.log otherwise. */
        const val EXTRA_SOURCE = "source"

        fun intent(context: Context, source: String? = null): Intent =
            Intent(context, LogsActivity::class.java).apply { source?.let { putExtra(EXTRA_SOURCE, it) } }
    }
}
