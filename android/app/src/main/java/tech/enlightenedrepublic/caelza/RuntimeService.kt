package tech.enlightenedrepublic.caelza

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import tech.enlightenedrepublic.caelza.body.AndroidSensors
import tech.enlightenedrepublic.caelza.body.BodyHome
import tech.enlightenedrepublic.caelza.body.BodyServer
import tech.enlightenedrepublic.caelza.body.BodyShell
import tech.enlightenedrepublic.caelza.body.BodyTools
import tech.enlightenedrepublic.caelza.body.ShizukuShell
import tech.enlightenedrepublic.caelza.guide.CaelCorpus
import tech.enlightenedrepublic.caelza.model.LlamaRuntime
import tech.enlightenedrepublic.caelza.model.ModelServe
import tech.enlightenedrepublic.caelza.model.ModelStore
import tech.enlightenedrepublic.caelza.runtime.CrashLoop
import tech.enlightenedrepublic.caelza.runtime.GatewayPairing
import tech.enlightenedrepublic.caelza.runtime.Gateway
import tech.enlightenedrepublic.caelza.runtime.RuntimeStore
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * The Runtime (`caelza daemon`) as a foreground service, with the supervisor's
 * ladder (`caelza_body/supervisor.py`): run the `current` binary, restart it
 * when it exits, on a crash loop point `current` back at `last-good` and
 * restart, halt when last-good itself loops or when another Runtime already
 * holds the gateway port. The installer asks for a restart after a new
 * version probed ok.
 *
 * It also hosts the Body (M7b): the phone's device tools over Shizuku as an
 * MCP server on loopback (`BodyServer`), started before the daemon so the
 * Runtime's `body` MCP server is there when it connects, and wired into the
 * config (`RuntimeStore.ensureBodyWiring`) with the token the Body created.
 */
class RuntimeService : Service() {
    enum class Phase { STOPPED, STARTING, RUNNING, HALTED }

    data class RuntimeState(
        val phase: Phase = Phase.STOPPED,
        val version: String? = null,
        val detail: String = "",
    )

    data class BodyState(
        val serving: Boolean = false,
        val port: Int = RuntimeStore.BODY_PORT,
        val tools: Int = 0,
        val detail: String = "",
    )

    /** The local model server (M7d): what `serve.json` names, whether llama-server answers on its port. */
    data class ModelState(
        val configured: Boolean = false,
        val serving: Boolean = false,
        val model: String? = null,
        val detail: String = "",
    )

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var store: RuntimeStore
    private var job: Job? = null
    private var process: Process? = null
    private var bodyServer: BodyServer? = null
    private var modelJob: Job? = null
    private var modelProcess: Process? = null
    private val modelCrashes = CrashLoop(n = 3, windowMs = 10 * 60_000)
    private val crashes = CrashLoop()
    private var lastGoodLooping = false
    @Volatile private var stopping = false
    @Volatile private var modelStopping = false

    override fun onCreate() {
        super.onCreate()
        store = RuntimeStore(filesDir)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, notification(getString(R.string.runtime_notification_title)))
        when (intent?.action) {
            ACTION_STOP -> {
                stopRuntime()
                stopModel()
                stopBody()
                _state.value = RuntimeState(Phase.STOPPED)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
            ACTION_RESTART -> {
                stopRuntime()
                crashes.reset()
                lastGoodLooping = false
                startBody()
                startModel()
                startRuntime()
            }
            else -> {
                startBody()
                startModel()
                if (job?.isActive != true) startRuntime()
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopRuntime()
        stopModel()
        stopBody()
        scope.cancel()
        super.onDestroy()
    }

    /**
     * The local model server (the first run's free door): when `serve.json`
     * names a model, run llama-server on it the way `serve.sh` does on Termux,
     * before the daemon, restarting it when it exits and giving up after three
     * exits in ten minutes. Nothing configured, or nothing installed, is a
     * status line; the daemon runs either way.
     */
    private fun startModel() {
        if (modelJob?.isActive == true) return
        val models = ModelStore(File(store.configDir, ModelStore.DIR))
        val serve = models.serve()
        if (serve == null) {
            _model.value = ModelState()
            return
        }
        val server = LlamaRuntime(filesDir).currentServer
        val model = File(models.dir, serve.model)
        if (server == null || !model.isFile) {
            _model.value = ModelState(
                configured = true, model = serve.model,
                detail = if (server == null) "llama-server is not installed" else "${serve.model} is missing",
            )
            return
        }
        modelStopping = false
        modelCrashes.reset()
        modelJob = scope.launch { superviseModel(server, model, serve) }
    }

    private suspend fun superviseModel(server: File, model: File, serve: ModelServe) {
        while (!modelStopping) {
            _model.value = ModelState(configured = true, model = model.name, detail = "loading")
            val proc = try {
                launchModel(server, model, serve)
            } catch (e: Exception) {
                _model.value = ModelState(configured = true, model = model.name, detail = "could not start llama-server: ${e.message}")
                return
            }
            modelProcess = proc
            while (proc.isAlive && !Gateway.healthy(serve.port, 1_000)) delay(1_000)
            if (proc.isAlive) _model.value = ModelState(configured = true, serving = true, model = model.name, detail = "serving on :${serve.port}")
            val code = proc.waitFor()
            modelProcess = null
            if (modelStopping) return
            val now = System.currentTimeMillis()
            modelCrashes.recordExit(now)
            if (modelCrashes.tripped(now)) {
                _model.value = ModelState(configured = true, model = model.name, detail = "llama-server exited $code three times; see logs/llama-server.log")
                return
            }
            _model.value = ModelState(configured = true, model = model.name, detail = "exited $code; restarting")
            delay(RESTART_DELAY_MS)
        }
    }

    private fun launchModel(server: File, model: File, serve: ModelServe): Process {
        store.logsDir.mkdirs()
        val log = File(store.logsDir, "llama-server.log")
        if (log.length() > LOG_ROTATE_BYTES) log.renameTo(File(store.logsDir, "llama-server.log.prev"))
        val pb = ProcessBuilder(LlamaRuntime.command(server, model, serve.port, serve.ctx))
            .directory(server.parentFile)
            .redirectErrorStream(true)
            .redirectOutput(ProcessBuilder.Redirect.appendTo(log))
        val env = pb.environment()
        env["HOME"] = filesDir.path
        env["TMPDIR"] = cacheDir.path
        env["LD_LIBRARY_PATH"] = server.parentFile?.path ?: ""
        return pb.start()
    }

    private fun stopModel() {
        modelStopping = true
        modelJob?.cancel()
        modelJob = null
        modelProcess?.let { proc ->
            proc.destroy()
            if (!proc.waitFor(5, TimeUnit.SECONDS)) proc.destroyForcibly()
        }
        modelProcess = null
        _model.value = ModelState()
    }

    /**
     * Serve the Body on loopback and make sure the Runtime's config names it.
     * A port something else holds (a Termux Body on the same phone) is a
     * status line, not a crash: the Runtime then talks to that Body.
     */
    private fun startBody() {
        if (bodyServer?.isRunning == true) return
        try {
            val home = BodyHome(File(filesDir, BodyHome.DIR_NAME))
            home.prune()
            val token = home.token()
            store.ensureBodyWiring(token)
            val tools = BodyTools(BodyShell(ShizukuShell()), home, AndroidSensors(applicationContext))
            val server = BodyServer(tools, token, log = { Log.w(TAG, it) })
            server.start()
            bodyServer = server
            _body.value = BodyState(serving = true, port = server.port, tools = tools.tools.size)
        } catch (e: Exception) {
            Log.w(TAG, "Body not serving", e)
            _body.value = BodyState(detail = "not serving: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    private fun stopBody() {
        bodyServer?.stop()
        bodyServer = null
        _body.value = BodyState()
    }

    private fun startRuntime() {
        stopping = false
        job = scope.launch { supervise() }
    }

    private fun stopRuntime() {
        stopping = true
        job?.cancel()
        job = null
        process?.let { proc ->
            proc.destroy()
            if (!proc.waitFor(5, TimeUnit.SECONDS)) proc.destroyForcibly()
        }
        process = null
    }

    private suspend fun supervise() {
        while (!stopping) {
            val binary = store.currentBinary
            if (binary == null) {
                halt(getString(R.string.status_not_installed))
                return
            }
            store.ensureConfig()
            val version = store.current
            _state.value = RuntimeState(Phase.STARTING, version)
            val proc = try {
                launchDaemon(binary)
            } catch (e: Exception) {
                recordCrash("could not start $version: ${e.message}")
                if (_state.value.phase == Phase.HALTED) return
                delay(RESTART_DELAY_MS)
                continue
            }
            process = proc
            _state.value = RuntimeState(Phase.RUNNING, version)
            updateNotification(getString(R.string.status_running, version ?: ""))
            scope.launch { loadCaelCorpus() }
            val code = withContextWait(proc)
            process = null
            if (stopping) return
            recordCrash("$version exited $code")
            if (_state.value.phase == Phase.HALTED) return
            delay(RESTART_DELAY_MS)
        }
    }

    /**
     * Cael's manual into his memory once the gateway answers: the bundled corpus, one upsert
     * per chunk, remembered by fingerprint so each version goes in once (CaelCorpus). Before
     * the first run has created agents.cael the gateway says so and the next start tries again.
     */
    private suspend fun loadCaelCorpus() {
        val port = Gateway.port(store.configDir)
        repeat(CORPUS_HEALTH_TRIES) {
            if (stopping) return
            if (Gateway.healthy(port)) {
                val token = when (val paired = GatewayPairing.forStore(store).ensureToken(port)) {
                    is GatewayPairing.Outcome.Paired -> paired.token
                    is GatewayPairing.Outcome.Off -> null
                    is GatewayPairing.Outcome.Failed -> {
                        Log.w(TAG, "gateway pairing: ${paired.detail}")
                        return
                    }
                }
                val result = try {
                    val jsonl = assets.open(CaelCorpus.ASSET).bufferedReader().readText()
                    CaelCorpus(store.configDir).load(jsonl, port, token)
                } catch (e: Exception) {
                    Log.w(TAG, "Cael's corpus not loaded", e)
                    return
                }
                if (!result.skipped) Log.i(TAG, "Cael's corpus: ${result.detail}")
                return
            }
            delay(1_000)
        }
    }

    private suspend fun withContextWait(proc: Process): Int {
        // waitFor blocks this IO thread; cancellation destroys the process from stopRuntime().
        return proc.waitFor()
    }

    private fun recordCrash(reason: String) {
        val now = System.currentTimeMillis()
        crashes.recordExit(now)
        if (!crashes.tripped(now)) {
            _state.update { it.copy(phase = Phase.STARTING, detail = reason) }
            return
        }
        val port = Gateway.port(store.configDir)
        if (Gateway.healthy(port)) {
            halt("another Runtime already serves the gateway on port $port; not rolling back")
            return
        }
        if (lastGoodLooping) {
            halt(getString(R.string.status_halted))
            return
        }
        val rolled = store.rollback()
        crashes.reset()
        lastGoodLooping = true
        _state.update {
            it.copy(phase = Phase.STARTING, detail = if (rolled != null) "crash loop: rolled back to last-good $rolled" else "crash loop, no other last-good; one more try")
        }
    }

    private fun halt(reason: String) {
        _state.value = RuntimeState(Phase.HALTED, store.current, reason)
        updateNotification(getString(R.string.runtime_notification_stopped) + ": " + reason)
    }

    private fun launchDaemon(binary: File): Process {
        store.logsDir.mkdirs()
        val log = File(store.logsDir, "daemon.log")
        if (log.length() > LOG_ROTATE_BYTES) log.renameTo(File(store.logsDir, "daemon.log.prev"))
        val pb = ProcessBuilder(binary.path, "daemon")
            .directory(filesDir)
            .redirectErrorStream(true)
            .redirectOutput(ProcessBuilder.Redirect.appendTo(log))
        val env = pb.environment()
        env["HOME"] = filesDir.path
        env["TMPDIR"] = cacheDir.path
        env["CAELZA_SUPERVISED"] = "1"
        env["TERM"] = "dumb"
        return pb.start()
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_monochrome)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private fun updateNotification(text: String) {
        try {
            NotificationManagerCompat.from(this).notify(NOTIFICATION_ID, notification(text))
        } catch (_: SecurityException) {
            // Notifications denied: the status strip still shows the state.
        }
    }

    companion object {
        private const val TAG = "caelza"
        /** How long the corpus loader waits for `/health` after the daemon starts, in seconds. */
        private const val CORPUS_HEALTH_TRIES = 90
        const val CHANNEL_ID = "runtime"
        const val NOTIFICATION_ID = 1
        const val ACTION_START = "tech.enlightenedrepublic.caelza.START"
        const val ACTION_STOP = "tech.enlightenedrepublic.caelza.STOP"
        const val ACTION_RESTART = "tech.enlightenedrepublic.caelza.RESTART"
        const val RESTART_DELAY_MS = 2_000L
        const val LOG_ROTATE_BYTES = 5L * 1024 * 1024

        private val _state = MutableStateFlow(RuntimeState())
        val state: StateFlow<RuntimeState> = _state
        private val _body = MutableStateFlow(BodyState())
        val body: StateFlow<BodyState> = _body
        private val _model = MutableStateFlow(ModelState())
        val model: StateFlow<ModelState> = _model

        fun start(context: Context) = send(context, ACTION_START)
        fun stop(context: Context) = send(context, ACTION_STOP)
        fun restart(context: Context) = send(context, ACTION_RESTART)

        private fun send(context: Context, action: String) {
            val intent = Intent(context, RuntimeService::class.java).setAction(action)
            ContextCompat.startForegroundService(context, intent)
        }
    }
}
