package tech.enlightenedrepublic.caelza.firstrun

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.NumberPicker
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import tech.enlightenedrepublic.caelza.R
import tech.enlightenedrepublic.caelza.RuntimeService
import tech.enlightenedrepublic.caelza.body.SensorPermissions
import tech.enlightenedrepublic.caelza.databinding.ActivityFirstRunBinding
import tech.enlightenedrepublic.caelza.logs.BugReport
import tech.enlightenedrepublic.caelza.model.HttpDownloader
import tech.enlightenedrepublic.caelza.model.LlamaPin
import tech.enlightenedrepublic.caelza.model.LlamaRuntime
import tech.enlightenedrepublic.caelza.model.ModelLadder
import tech.enlightenedrepublic.caelza.model.ModelServe
import tech.enlightenedrepublic.caelza.model.ModelStore
import tech.enlightenedrepublic.caelza.runtime.CaelzaCli
import tech.enlightenedrepublic.caelza.runtime.ProcessProber
import tech.enlightenedrepublic.caelza.runtime.ReleaseInstaller
import tech.enlightenedrepublic.caelza.runtime.RuntimeStore
import tech.enlightenedrepublic.caelza.shizuku.ShizukuStatus
import java.io.File

/**
 * The first run, led by Cael (design §5): the Runtime installed, a brain
 * chosen (free and local, or bring your own key), Shizuku explained,
 * permissions asked for with their reasons, the battery exemption, a word
 * about hubs, then the Runtime started and the dashboard shown. Every step
 * can be skipped and done later; the shell's `Set up with Cael` brings it back.
 */
class FirstRunActivity : AppCompatActivity() {
    private lateinit var b: ActivityFirstRunBinding
    private lateinit var store: RuntimeStore
    private var step = FirstRun.Step.HELLO
    private var door: FirstRun.Door? = null
    private var busy = false
    private val lines = mutableListOf<String>()
    private var lastProgressAt = 0L
    private val pick: ModelLadder.Pick by lazy { ModelLadder.pick(ModelLadder.ramMb(totalRam())) }
    /** The key door's wheels: the curated providers and their picks (bundle/models.json, bundled). */
    private val providers: List<ModelCatalog.Provider> by lazy { ModelCatalog.load { assets.open(it) } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityFirstRunBinding.inflate(layoutInflater)
        setContentView(b.root)
        store = RuntimeStore(filesDir)
        // Recreated (not a rotation, which the manifest keeps in place): back to the step the owner was on.
        savedInstanceState?.getString(STATE_STEP)?.let { step = runCatching { FirstRun.Step.valueOf(it) }.getOrDefault(step) }
        savedInstanceState?.getString(STATE_DOOR)?.let { door = runCatching { FirstRun.Door.valueOf(it) }.getOrNull() }
        b.primary.setOnClickListener { onPrimary() }
        b.secondary.setOnClickListener { onSecondary() }
        b.tertiary.setOnClickListener { onTertiary() }
        render()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(STATE_STEP, step.name)
        door?.let { outState.putString(STATE_DOOR, it.name) }
    }

    override fun onResume() {
        super.onResume()
        if (!busy) render()
    }

    @Deprecated("Deprecated in Java")
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        render()
    }

    private fun totalRam(): Long {
        val info = ActivityManager.MemoryInfo()
        getSystemService(ActivityManager::class.java)?.getMemoryInfo(info)
        return info.totalMem
    }

    private fun prefs() = getSharedPreferences(FirstRun.PREFS, Context.MODE_PRIVATE)

    // --- rendering ----------------------------------------------------------------

    private fun show(title: Int, cael: String, primary: String) {
        b.title.text = getString(title)
        b.cael.text = cael
        b.primary.text = primary
    }

    private fun secondary(text: Int) {
        b.secondary.text = getString(text)
        b.secondary.visibility = View.VISIBLE
    }

    private fun tertiary(text: Int) {
        b.tertiary.text = getString(text)
        b.tertiary.visibility = View.VISIBLE
    }

    private fun render() {
        val steps = FirstRun.Step.values()
        b.stepLabel.text = getString(R.string.fr_step, step.ordinal + 1, steps.size)
        b.wheels.visibility = View.GONE
        b.modelInput.visibility = View.GONE
        b.keyInput.visibility = View.GONE
        b.secondary.visibility = View.GONE
        b.tertiary.visibility = View.GONE
        b.detail.text = lines.takeLast(6).joinToString("\n")
        if (!busy) b.progress.text = ""
        b.primary.isEnabled = !busy
        b.secondary.isEnabled = !busy
        b.tertiary.isEnabled = !busy
        when (step) {
            FirstRun.Step.HELLO -> show(R.string.fr_hello_title, getString(R.string.fr_hello_body), getString(R.string.fr_next))
            FirstRun.Step.RUNTIME -> {
                val installed = store.currentBinary != null
                if (installed) {
                    show(R.string.fr_runtime_title, getString(R.string.fr_runtime_installed, store.current ?: ""), getString(R.string.fr_next))
                } else {
                    show(R.string.fr_runtime_title, getString(R.string.fr_runtime_body), getString(R.string.action_install))
                    tertiary(R.string.fr_skip)
                }
            }
            FirstRun.Step.BRAIN -> when (door) {
                null -> {
                    show(R.string.fr_brain_title, getString(R.string.fr_brain_body), getString(R.string.fr_door_local))
                    secondary(R.string.fr_door_key)
                    tertiary(R.string.fr_skip)
                }
                FirstRun.Door.LOCAL -> {
                    val mib = (pick.downloadBytes + LlamaPin.CURRENT.bytes) / 1024 / 1024
                    show(R.string.fr_local_title, FirstRun.pickLine(pick) + "\n\n" + getString(R.string.fr_local_more), getString(R.string.fr_download, mib))
                    tertiary(R.string.fr_back)
                }
                FirstRun.Door.KEY -> {
                    show(R.string.fr_key_title, getString(R.string.fr_key_body), getString(R.string.fr_save))
                    showKeyForm()
                    tertiary(R.string.fr_back)
                }
            }
            FirstRun.Step.SHIZUKU -> {
                show(R.string.fr_shizuku_title, getString(R.string.fr_shizuku_body), getString(R.string.fr_open_shizuku))
                secondary(R.string.action_shizuku)
                tertiary(R.string.fr_next)
                b.detail.text = "${getString(R.string.status_shizuku_prefix)} · ${ShizukuStatus.label(ShizukuStatus.state())}"
            }
            FirstRun.Step.PERMISSIONS -> {
                val missing = SensorPermissions.missing(this)
                show(R.string.fr_permissions_title, getString(R.string.fr_permissions_body), getString(if (missing.isEmpty()) R.string.fr_next else R.string.action_grant))
                if (missing.isNotEmpty()) tertiary(R.string.fr_skip)
                b.detail.text = if (missing.isEmpty()) getString(R.string.status_sensors_ready) else getString(R.string.status_sensors_missing, missing.joinToString(", "))
            }
            FirstRun.Step.BATTERY -> {
                val exempt = batteryExempt()
                show(R.string.fr_battery_title, getString(R.string.fr_battery_body), getString(if (exempt) R.string.fr_next else R.string.fr_keep_awake))
                if (!exempt) tertiary(R.string.fr_skip)
                b.detail.text = getString(if (exempt) R.string.fr_battery_exempt else R.string.fr_battery_not_exempt)
            }
            FirstRun.Step.HUB -> show(R.string.fr_hub_title, getString(R.string.fr_hub_body), getString(R.string.fr_next))
            FirstRun.Step.START -> show(R.string.fr_start_title, getString(R.string.fr_start_body), getString(R.string.fr_start))
        }
    }

    /** The key door: two wheels (the provider, then one of its models with Cael's picks on top) and the key box. */
    private fun showKeyForm() {
        if (b.providerWheel.displayedValues == null) {
            wheel(b.providerWheel, providers.map { it.label })
            b.providerWheel.setOnValueChangedListener { _, _, _ -> showModels(reset = true) }
            b.modelWheel.setOnValueChangedListener { _, _, _ -> modelChanged() }
            showModels(reset = true)
        }
        b.wheels.visibility = View.VISIBLE
        b.keyInput.visibility = View.VISIBLE
        b.modelInput.visibility = if (typingModel()) View.VISIBLE else View.GONE
    }

    /** A NumberPicker as a wheel of names: no wrap, no keyboard editing of the row. */
    private fun wheel(w: NumberPicker, rows: List<String>) {
        w.displayedValues = null
        w.minValue = 0
        w.maxValue = rows.size - 1
        w.displayedValues = rows.toTypedArray()
        w.wrapSelectorWheel = false
        w.descendantFocusability = ViewGroup.FOCUS_BLOCK_DESCENDANTS
    }

    private fun provider(): ModelCatalog.Provider = providers[b.providerWheel.value.coerceIn(0, providers.size - 1)]

    /** The model wheel for the chosen provider: its picks, then "Type a name…" as the last row. */
    private fun showModels(reset: Boolean) {
        val p = provider()
        wheel(b.modelWheel, p.models.map { it.row } + getString(R.string.fr_type_model))
        if (reset) b.modelWheel.value = p.models.indexOf(p.best).coerceAtLeast(0)
        b.keyInput.hint = getString(R.string.fr_key_hint, p.keyPrefix, p.where)
        modelChanged()
    }

    /** The wheel rests on the last row: the owner types the model's name. */
    private fun typingModel(): Boolean = b.modelWheel.value >= provider().models.size

    private fun modelChanged() {
        if (typingModel()) {
            b.modelLine.text = ""
            b.modelInput.visibility = View.VISIBLE
            b.modelInput.requestFocus()
        } else {
            b.modelLine.text = provider().models[b.modelWheel.value].id
            b.modelInput.visibility = View.GONE
        }
    }

    private fun chosenModel(): String =
        if (typingModel()) b.modelInput.text.toString().trim() else provider().models[b.modelWheel.value].id

    private fun batteryExempt(): Boolean =
        getSystemService(PowerManager::class.java)?.isIgnoringBatteryOptimizations(packageName) ?: false

    // --- the buttons ---------------------------------------------------------------

    private fun onPrimary() {
        if (busy) return
        when (step) {
            FirstRun.Step.HELLO, FirstRun.Step.HUB -> advance()
            FirstRun.Step.RUNTIME -> if (store.currentBinary != null) advance() else installRuntime()
            FirstRun.Step.BRAIN -> when (door) {
                null -> {
                    door = FirstRun.Door.LOCAL
                    render()
                }
                FirstRun.Door.LOCAL -> setUpLocal()
                FirstRun.Door.KEY -> saveKey()
            }
            FirstRun.Step.SHIZUKU -> openShizuku()
            FirstRun.Step.PERMISSIONS -> if (SensorPermissions.missing(this).isEmpty()) advance() else { if (!SensorPermissions.request(this)) render() }
            FirstRun.Step.BATTERY -> if (batteryExempt()) advance() else requestBatteryExemption()
            FirstRun.Step.START -> finishSetup()
        }
    }

    private fun onSecondary() {
        if (busy) return
        when (step) {
            FirstRun.Step.BRAIN -> {
                door = FirstRun.Door.KEY
                render()
            }
            FirstRun.Step.SHIZUKU -> {
                if (!ShizukuStatus.request()) render()
            }
            else -> Unit
        }
    }

    private fun onTertiary() {
        if (busy) return
        if (step == FirstRun.Step.BRAIN && door != null) {
            door = null
            lines.clear()
            render()
        } else {
            advance()
        }
    }

    private fun advance() {
        door = null
        lines.clear()
        val next = FirstRun.next(step)
        if (next == null) {
            finishSetup()
            return
        }
        step = next
        render()
    }

    private fun line(text: String) {
        lines += text
        runOnUiThread {
            b.detail.text = lines.takeLast(6).joinToString("\n")
            b.progress.text = ""
        }
    }

    private fun progress(done: Long, total: Long) {
        val now = System.currentTimeMillis()
        if (done < total && now - lastProgressAt < 400) return
        lastProgressAt = now
        val pct = if (total > 0) (done * 100 / total).toInt() else 0
        runOnUiThread { b.progress.text = getString(R.string.fr_progress, pct, done / 1024 / 1024, total / 1024 / 1024) }
    }

    /** The installer's and the local door's lines go here too: the Logs screen's bug report carries what went wrong. */
    private val installLog: File get() = File(store.logsDir, BugReport.INSTALL_LOG)

    private fun work(block: suspend () -> Unit) {
        busy = true
        // A gigabyte over a phone's connection takes minutes: the screen stays on so the
        // download is not left to Doze halfway (the work runs in this activity, not a service).
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        render()
        lifecycleScope.launch {
            val error = try {
                withContext(Dispatchers.IO) { block() }
                null
            } catch (e: Exception) {
                e
            }
            busy = false
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            if (error != null) {
                val what = error.message ?: error.javaClass.simpleName
                BugReport.append(installLog, "failed: $what")
                line(getString(R.string.fr_failed, what))
            }
            render()
        }
    }

    // --- the steps' actions ---------------------------------------------------------

    /** A line for the owner and for the bug report. */
    private fun say(text: String) {
        line(text)
        BugReport.append(installLog, text)
    }

    private fun installRuntime() = work {
        BugReport.append(installLog, "== update from the first run")
        val result = ReleaseInstaller(store, prober = ProcessProber(home = filesDir), log = ::say).update()
        say(if (result.promoted) getString(R.string.install_done, result.version) else "${result.version}: ${result.detail}")
    }

    /** The free, local door: llama.cpp's Android build, the pick's GGUFs, the Runtime pointed at them, Cael created. */
    private fun setUpLocal() {
        val binary = store.currentBinary
        if (binary == null) {
            line(getString(R.string.fr_needs_runtime))
            step = FirstRun.Step.RUNTIME
            door = null
            render()
            return
        }
        work {
            BugReport.append(installLog, "== the local door from the first run (${pick.ramMb} MiB RAM: ${pick.agent.name})")
            val downloader = HttpDownloader()
            val llama = LlamaRuntime(filesDir)
            say(getString(R.string.fr_getting, "llama.cpp ${LlamaPin.CURRENT.tag}", LlamaPin.CURRENT.bytes / 1024 / 1024))
            llama.install(downloader, ::progress)
            val models = ModelStore(File(store.configDir, ModelStore.DIR))
            for (g in pick.files) {
                say(getString(R.string.fr_getting, g.file, g.mib))
                models.download(g, downloader, ::progress)
                say(getString(R.string.fr_verified, g.file))
            }
            models.writeServe(ModelServe(pick.agent.file))
            CaelzaCli(binary, filesDir, log = ::say).configure(FirstRun.localConfig(pick))
            CaelzaCli.writeCaelPersona(store.configDir, assets.open(CAEL_SOUL).bufferedReader().readText())
            say(getString(R.string.fr_that_worked_local, pick.agent.name))
            runOnUiThread { advance() }
        }
    }

    /** Bring your own: the key and model behind `<provider>.default`, the agent and Cael on it. */
    private fun saveKey() {
        val binary = store.currentBinary
        if (binary == null) {
            line(getString(R.string.fr_needs_runtime))
            step = FirstRun.Step.RUNTIME
            door = null
            render()
            return
        }
        val p = provider()
        val key = b.keyInput.text.toString()
        val model = chosenModel()
        if (!FirstRun.keyLooksRight(key)) {
            line(getString(R.string.fr_key_short))
            render()
            return
        }
        work {
            CaelzaCli(binary, filesDir, log = ::line).configure(FirstRun.keyConfig(p, model, key))
            ModelStore(File(store.configDir, ModelStore.DIR)).clearServe()
            CaelzaCli.writeCaelPersona(store.configDir, assets.open(CAEL_SOUL).bufferedReader().readText())
            line(getString(R.string.fr_that_worked_key, p.label))
            runOnUiThread { advance() }
        }
    }

    private fun openShizuku() {
        val launch = packageManager.getLaunchIntentForPackage(SHIZUKU_PACKAGE)
        try {
            startActivity(launch ?: Intent(Intent.ACTION_VIEW, Uri.parse(SHIZUKU_SITE)))
        } catch (_: Exception) {
            line(getString(R.string.fr_shizuku_missing))
        }
    }

    private fun requestBatteryExemption() {
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        } catch (_: Exception) {
            try {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (_: Exception) {
                line(getString(R.string.fr_battery_no_screen))
            }
        }
    }

    private fun finishSetup() {
        prefs().edit().putBoolean(FirstRun.DONE, true).apply()
        if (store.currentBinary != null) RuntimeService.start(this)
        finish()
    }

    companion object {
        private const val STATE_STEP = "step"
        private const val STATE_DOOR = "door"
        const val CAEL_SOUL = "cael.system.md"
        const val SHIZUKU_PACKAGE = "moe.shizuku.privileged.api"
        const val SHIZUKU_SITE = "https://shizuku.rikka.app/"
    }
}
