package tech.enlightenedrepublic.caelza.firstrun

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.widget.RadioButton
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import tech.enlightenedrepublic.caelza.R
import tech.enlightenedrepublic.caelza.RuntimeService
import tech.enlightenedrepublic.caelza.body.SensorPermissions
import tech.enlightenedrepublic.caelza.databinding.ActivityFirstRunBinding
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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityFirstRunBinding.inflate(layoutInflater)
        setContentView(b.root)
        store = RuntimeStore(filesDir)
        b.primary.setOnClickListener { onPrimary() }
        b.secondary.setOnClickListener { onSecondary() }
        b.tertiary.setOnClickListener { onTertiary() }
        render()
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
        b.choices.visibility = View.GONE
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

    private fun showKeyForm() {
        if (b.choices.childCount == 0) {
            FirstRun.PROVIDERS.forEachIndexed { i, p ->
                b.choices.addView(RadioButton(this).apply {
                    id = View.generateViewId()
                    tag = i
                    text = p.label
                    setTextColor(getColor(R.color.text))
                })
            }
            (b.choices.getChildAt(0) as RadioButton).isChecked = true
            b.modelInput.setText(FirstRun.PROVIDERS[0].defaultModel)
            b.choices.setOnCheckedChangeListener { group, checkedId ->
                val p = provider()
                val current = b.modelInput.text.toString().trim()
                if (current.isEmpty() || FirstRun.PROVIDERS.any { it.defaultModel == current }) b.modelInput.setText(p.defaultModel)
                b.keyInput.hint = getString(R.string.fr_key_hint, p.keyPrefix, p.where)
                group.findViewById<RadioButton>(checkedId)?.requestFocus()
            }
        }
        val p = provider()
        b.keyInput.hint = getString(R.string.fr_key_hint, p.keyPrefix, p.where)
        b.choices.visibility = View.VISIBLE
        b.modelInput.visibility = View.VISIBLE
        b.keyInput.visibility = View.VISIBLE
    }

    private fun provider(): FirstRun.Provider {
        val checked = b.choices.findViewById<RadioButton>(b.choices.checkedRadioButtonId)
        return FirstRun.PROVIDERS[(checked?.tag as? Int) ?: 0]
    }

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

    private fun work(block: suspend () -> Unit) {
        busy = true
        render()
        lifecycleScope.launch {
            val error = try {
                withContext(Dispatchers.IO) { block() }
                null
            } catch (e: Exception) {
                e
            }
            busy = false
            if (error != null) line(getString(R.string.fr_failed, error.message ?: error.javaClass.simpleName))
            render()
        }
    }

    // --- the steps' actions ---------------------------------------------------------

    private fun installRuntime() = work {
        val result = ReleaseInstaller(store, prober = ProcessProber(home = filesDir), log = ::line).update()
        line(if (result.promoted) getString(R.string.install_done, result.version) else "${result.version}: ${result.detail}")
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
            val downloader = HttpDownloader()
            val llama = LlamaRuntime(filesDir)
            line(getString(R.string.fr_getting, "llama.cpp ${LlamaPin.CURRENT.tag}", LlamaPin.CURRENT.bytes / 1024 / 1024))
            llama.install(downloader, ::progress)
            val models = ModelStore(File(store.configDir, ModelStore.DIR))
            for (g in pick.files) {
                line(getString(R.string.fr_getting, g.file, g.mib))
                models.download(g, downloader, ::progress)
                line(getString(R.string.fr_verified, g.file))
            }
            models.writeServe(ModelServe(pick.agent.file))
            CaelzaCli(binary, filesDir, ::line).configure(FirstRun.localConfig(pick))
            CaelzaCli.writeCaelPersona(store.configDir, assets.open(CAEL_SOUL).bufferedReader().readText())
            line(getString(R.string.fr_that_worked_local, pick.agent.name))
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
        val model = b.modelInput.text.toString()
        if (!FirstRun.keyLooksRight(key)) {
            line(getString(R.string.fr_key_short))
            render()
            return
        }
        work {
            CaelzaCli(binary, filesDir, ::line).configure(FirstRun.keyConfig(p, model, key))
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
        const val CAEL_SOUL = "cael.system.md"
        const val SHIZUKU_PACKAGE = "moe.shizuku.privileged.api"
        const val SHIZUKU_SITE = "https://shizuku.rikka.app/"
    }
}
