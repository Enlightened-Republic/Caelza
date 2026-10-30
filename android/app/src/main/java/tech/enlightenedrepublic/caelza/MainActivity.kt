package tech.enlightenedrepublic.caelza

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.View
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.addCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import rikka.shizuku.Shizuku
import tech.enlightenedrepublic.caelza.databinding.ActivityMainBinding
import tech.enlightenedrepublic.caelza.runtime.Gateway
import tech.enlightenedrepublic.caelza.runtime.ProcessProber
import tech.enlightenedrepublic.caelza.runtime.ReleaseInstaller
import tech.enlightenedrepublic.caelza.runtime.RuntimeStore
import tech.enlightenedrepublic.caelza.shizuku.ShizukuStatus

/**
 * The shell: a status strip (the Runtime, Shizuku, start/stop, update) over
 * the dashboard, which is the Runtime's own web app served by its gateway on
 * loopback. Until the gateway answers, the shell says what to do next.
 */
class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var store: RuntimeStore
    private var dashboardShown = false
    private var installing = false

    private val shizukuListener = Shizuku.OnRequestPermissionResultListener { _, _ -> renderShizuku() }
    private val binderListener = Shizuku.OnBinderReceivedListener { renderShizuku() }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        store = RuntimeStore(filesDir)

        binding.dashboard.apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            webViewClient = WebViewClient()
            WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        }
        onBackPressedDispatcher.addCallback(this) {
            if (binding.dashboard.visibility == View.VISIBLE && binding.dashboard.canGoBack()) binding.dashboard.goBack() else finish()
        }

        binding.toggleButton.setOnClickListener {
            when (RuntimeService.state.value.phase) {
                RuntimeService.Phase.RUNNING, RuntimeService.Phase.STARTING -> RuntimeService.stop(this)
                else -> if (store.currentBinary != null) RuntimeService.start(this) else install()
            }
        }
        binding.updateButton.setOnClickListener { install() }
        binding.primaryAction.setOnClickListener {
            if (store.currentBinary == null) install() else RuntimeService.start(this)
        }
        binding.shizukuAction.setOnClickListener {
            if (!ShizukuStatus.request()) renderShizuku()
        }

        try {
            Shizuku.addRequestPermissionResultListener(shizukuListener)
            Shizuku.addBinderReceivedListenerSticky(binderListener)
        } catch (_: Throwable) {
            // Shizuku not installed: the status says so.
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch { RuntimeService.state.collect { render(it) } }
                launch { RuntimeService.body.collect { renderShizuku() } }
                launch { watchGateway() }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        renderShizuku()
        render(RuntimeService.state.value)
    }

    override fun onDestroy() {
        try {
            Shizuku.removeRequestPermissionResultListener(shizukuListener)
            Shizuku.removeBinderReceivedListener(binderListener)
        } catch (_: Throwable) {
        }
        super.onDestroy()
    }

    private fun render(state: RuntimeService.RuntimeState) {
        val installed = store.currentBinary != null
        val label = when (state.phase) {
            RuntimeService.Phase.STOPPED -> if (installed) getString(R.string.status_stopped) else getString(R.string.status_not_installed)
            RuntimeService.Phase.STARTING -> getString(R.string.status_starting)
            RuntimeService.Phase.RUNNING -> getString(R.string.status_running, state.version ?: "")
            RuntimeService.Phase.HALTED -> getString(R.string.status_halted)
        }
        binding.runtimeStatus.text = "${getString(R.string.status_runtime_prefix)} · $label"
        val running = state.phase == RuntimeService.Phase.RUNNING || state.phase == RuntimeService.Phase.STARTING
        binding.toggleButton.text = getString(if (running) R.string.action_stop else R.string.action_start)
        binding.toggleButton.isEnabled = !installing
        binding.updateButton.text = getString(if (installed) R.string.action_update else R.string.action_install)
        binding.updateButton.isEnabled = !installing
        binding.primaryAction.text = getString(if (installed) R.string.action_start else R.string.action_install)
        binding.primaryAction.isEnabled = !installing && !running
        binding.emptyBody.text = when {
            !installed -> getString(R.string.empty_body)
            running -> getString(R.string.waiting_body)
            state.detail.isNotEmpty() -> state.detail
            else -> getString(R.string.empty_body)
        }
        if (!running && dashboardShown) showDashboard(false)
    }

    /** The Body line: whether it serves (tools, port) and where Shizuku, its privilege, stands. */
    private fun renderShizuku() {
        val state = ShizukuStatus.state()
        val body = RuntimeService.body.value
        val serving = when {
            body.serving -> getString(R.string.status_body_serving, body.tools, body.port)
            body.detail.isNotEmpty() -> body.detail
            else -> getString(R.string.status_body_off)
        }
        binding.shizukuStatus.text =
            "${getString(R.string.status_body_prefix)} · $serving · ${getString(R.string.status_shizuku_prefix)} ${ShizukuStatus.label(state)}"
        binding.shizukuAction.visibility = if (state == ShizukuStatus.State.READY) View.GONE else View.VISIBLE
    }

    /** Show the dashboard as soon as the gateway answers; drop back to the shell when it stops. */
    private suspend fun watchGateway() {
        while (currentCoroutineContextIsActive()) {
            val phase = RuntimeService.state.value.phase
            val running = phase == RuntimeService.Phase.RUNNING || phase == RuntimeService.Phase.STARTING
            if (running) {
                val port = Gateway.port(store.configDir)
                val healthy = withContext(Dispatchers.IO) { Gateway.healthy(port) }
                if (healthy && !dashboardShown) {
                    binding.dashboard.loadUrl(Gateway.url(port))
                    showDashboard(true)
                } else if (!healthy && dashboardShown) {
                    showDashboard(false)
                }
            }
            delay(if (dashboardShown) 5_000 else 1_500)
        }
    }

    private suspend fun currentCoroutineContextIsActive(): Boolean = kotlinx.coroutines.currentCoroutineContext().isActive

    private fun showDashboard(show: Boolean) {
        dashboardShown = show
        binding.dashboard.visibility = if (show) View.VISIBLE else View.GONE
        binding.emptyState.visibility = if (show) View.GONE else View.VISIBLE
    }

    /** Pull the latest release through the guard's pipeline, then restart the Runtime on it. */
    private fun install() {
        if (installing) return
        installing = true
        render(RuntimeService.state.value)
        binding.progress.text = getString(R.string.install_progress)
        lifecycleScope.launch {
            val lines = mutableListOf<String>()
            val result = withContext(Dispatchers.IO) {
                try {
                    val installer = ReleaseInstaller(
                        store,
                        prober = ProcessProber(home = filesDir),
                        log = { line ->
                            lines += line
                            runOnUiThread { binding.progress.text = lines.takeLast(6).joinToString("\n") }
                        },
                    )
                    Result.success(installer.update())
                } catch (e: Exception) {
                    Result.failure(e)
                }
            }
            installing = false
            result.fold(
                onSuccess = { r ->
                    binding.progress.text = if (r.promoted) getString(R.string.install_done, r.version) else "${r.version}: ${r.detail}"
                    if (r.promoted) RuntimeService.restart(this@MainActivity)
                },
                onFailure = { e -> binding.progress.text = getString(R.string.install_failed, e.message ?: e.javaClass.simpleName) },
            )
            render(RuntimeService.state.value)
        }
    }
}
