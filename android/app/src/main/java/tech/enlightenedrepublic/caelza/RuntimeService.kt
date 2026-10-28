package tech.enlightenedrepublic.caelza

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
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
import tech.enlightenedrepublic.caelza.runtime.CrashLoop
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
 */
class RuntimeService : Service() {
    enum class Phase { STOPPED, STARTING, RUNNING, HALTED }

    data class RuntimeState(
        val phase: Phase = Phase.STOPPED,
        val version: String? = null,
        val detail: String = "",
    )

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var store: RuntimeStore
    private var job: Job? = null
    private var process: Process? = null
    private val crashes = CrashLoop()
    private var lastGoodLooping = false
    @Volatile private var stopping = false

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
                _state.value = RuntimeState(Phase.STOPPED)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
            ACTION_RESTART -> {
                stopRuntime()
                crashes.reset()
                lastGoodLooping = false
                startRuntime()
            }
            else -> if (job?.isActive != true) startRuntime()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopRuntime()
        scope.cancel()
        super.onDestroy()
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
            val code = withContextWait(proc)
            process = null
            if (stopping) return
            recordCrash("$version exited $code")
            if (_state.value.phase == Phase.HALTED) return
            delay(RESTART_DELAY_MS)
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
            .setSmallIcon(R.drawable.ic_launcher_foreground)
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
        const val CHANNEL_ID = "runtime"
        const val NOTIFICATION_ID = 1
        const val ACTION_START = "tech.enlightenedrepublic.caelza.START"
        const val ACTION_STOP = "tech.enlightenedrepublic.caelza.STOP"
        const val ACTION_RESTART = "tech.enlightenedrepublic.caelza.RESTART"
        const val RESTART_DELAY_MS = 2_000L
        const val LOG_ROTATE_BYTES = 5L * 1024 * 1024

        private val _state = MutableStateFlow(RuntimeState())
        val state: StateFlow<RuntimeState> = _state

        fun start(context: Context) = send(context, ACTION_START)
        fun stop(context: Context) = send(context, ACTION_STOP)
        fun restart(context: Context) = send(context, ACTION_RESTART)

        private fun send(context: Context, action: String) {
            val intent = Intent(context, RuntimeService::class.java).setAction(action)
            ContextCompat.startForegroundService(context, intent)
        }
    }
}
