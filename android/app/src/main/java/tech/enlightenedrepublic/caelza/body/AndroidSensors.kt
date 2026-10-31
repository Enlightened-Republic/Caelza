package tech.enlightenedrepublic.caelza.body

import android.Manifest
import android.app.Notification
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.ImageFormat
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.media.ImageReader
import android.media.MediaRecorder
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Size
import android.view.Surface
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ExecutionException
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

/**
 * The phone's sensors through the normal Android APIs (design §4), answering
 * in the shapes `termux-api` prints so the Body's tools, the playbooks and
 * the dashboard's Bodies page see no difference: `BatteryManager` for the
 * battery, the bound [CaelzaNotificationListener] for the status bar,
 * `ClipboardManager`, `LocationManager` and `WifiManager`, camera2 for a
 * photo, `MediaRecorder` for the microphone, `TextToSpeech`, and the camera's
 * torch mode. Every permission the owner has not granted is a
 * [SensorUnavailable] naming where to grant it. Not unit-tested: these are
 * the framework calls themselves; the tools over them are tested with a fake.
 */
class AndroidSensors(context: Context) : Sensors {
    private val context: Context = context.applicationContext
    private val thread: HandlerThread by lazy { HandlerThread("caelza-sensors").apply { start() } }
    private val handler: Handler by lazy { Handler(thread.looper) }
    private val main = Handler(Looper.getMainLooper())

    private fun requirePermission(sensor: String) {
        val permission = SensorPermissions.RUNTIME[sensor] ?: return
        if (!SensorPermissions.granted(context, permission)) throw SensorUnavailable(SensorPermissions.needs(sensor))
    }

    // --- battery ----------------------------------------------------------------

    override fun battery(): JSONObject {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ?: throw SensorUnavailable("the battery state is not available right now")
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, 100)
        val plugged = when (intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0)) {
            0 -> "UNPLUGGED"
            BatteryManager.BATTERY_PLUGGED_AC -> "PLUGGED_AC"
            BatteryManager.BATTERY_PLUGGED_USB -> "PLUGGED_USB"
            BatteryManager.BATTERY_PLUGGED_WIRELESS -> "PLUGGED_WIRELESS"
            else -> "PLUGGED"
        }
        val current = try {
            context.getSystemService(BatteryManager::class.java)?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW) ?: 0
        } catch (_: Exception) {
            0
        }
        return JSONObject()
            .put("health", HEALTH[intent.getIntExtra(BatteryManager.EXTRA_HEALTH, 0)] ?: "UNKNOWN")
            .put("percentage", if (level >= 0 && scale > 0) level * 100 / scale else JSONObject.NULL)
            .put("plugged", plugged)
            .put("status", STATUS[intent.getIntExtra(BatteryManager.EXTRA_STATUS, 1)] ?: "UNKNOWN")
            .put("temperature", intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) / 10.0)
            .put("current", current)
    }

    // --- notifications ------------------------------------------------------------

    override fun notifications(): JSONArray {
        if (!CaelzaNotificationListener.enabled(context)) throw SensorUnavailable(SensorPermissions.needs("notifications"))
        val list = CaelzaNotificationListener.snapshot()
            ?: throw SensorUnavailable(
                "notification access is on but Android has not connected the listener yet; " +
                    "try again in a moment (turning the access off and on reconnects it)",
            )
        val format = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
        val out = JSONArray()
        for (sbn in list) {
            val n = sbn.notification
            val extras = n.extras
            val content = extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: extras.getCharSequence(Notification.EXTRA_TEXT)
            out.put(
                JSONObject()
                    .put("id", sbn.id)
                    .put("tag", sbn.tag ?: JSONObject.NULL)
                    .put("key", sbn.key)
                    .put("group", n.group ?: JSONObject.NULL)
                    .put("packageName", sbn.packageName)
                    .put("title", extras.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: "")
                    .put("content", content?.toString() ?: "")
                    .put("when", format.format(Date(n.`when`))),
            )
        }
        return out
    }

    // --- clipboard ----------------------------------------------------------------

    private val clipboard: ClipboardManager
        get() = context.getSystemService(ClipboardManager::class.java) ?: throw SensorUnavailable("this phone has no clipboard service")

    override fun clipboardGet(): String {
        val clip = clipboard.primaryClip
            ?: throw SensorUnavailable(
                "the clipboard is empty, or Caelza is not on screen: from Android 10 only the app in front may read it; open Caelza and try again",
            )
        if (clip.itemCount == 0) return ""
        return clip.getItemAt(0).coerceToText(context)?.toString() ?: ""
    }

    override fun clipboardSet(text: String) {
        clipboard.setPrimaryClip(ClipData.newPlainText("caelza", text))
    }

    // --- location ------------------------------------------------------------------

    override fun location(provider: String): JSONObject {
        if (!SensorPermissions.granted(context, Manifest.permission.ACCESS_FINE_LOCATION) &&
            !SensorPermissions.granted(context, Manifest.permission.ACCESS_COARSE_LOCATION)
        ) {
            throw SensorUnavailable(SensorPermissions.needs("location"))
        }
        val manager = context.getSystemService(LocationManager::class.java) ?: throw SensorUnavailable("this phone has no location service")
        val name = if (provider == "gps") LocationManager.GPS_PROVIDER else LocationManager.NETWORK_PROVIDER
        if (!manager.isProviderEnabled(name)) throw SensorUnavailable("the $provider location provider is off: turn Location on in Settings")
        val future = CompletableFuture<Location>()
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                manager.getCurrentLocation(name, null, context.mainExecutor) { location ->
                    if (location != null) future.complete(location) else future.completeExceptionally(SensorUnavailable("no $provider fix"))
                }
            } else {
                @Suppress("DEPRECATION")
                manager.requestSingleUpdate(
                    name,
                    object : LocationListener {
                        override fun onLocationChanged(location: Location) {
                            future.complete(location)
                        }
                    },
                    Looper.getMainLooper(),
                )
            }
        } catch (_: SecurityException) {
            throw SensorUnavailable(SensorPermissions.needs("location"))
        }
        val location = try {
            future.get(LOCATION_TIMEOUT_S, TimeUnit.SECONDS)
        } catch (_: TimeoutException) {
            lastKnown(manager, name)
                ?: throw SensorUnavailable("no $provider fix within ${LOCATION_TIMEOUT_S}s (indoors? mode='network' is quicker)")
        } catch (e: ExecutionException) {
            throw (e.cause as? SensorUnavailable) ?: SensorUnavailable("location failed: ${e.cause?.message}")
        }
        return JSONObject()
            .put("latitude", location.latitude)
            .put("longitude", location.longitude)
            .put("altitude", location.altitude)
            .put("accuracy", location.accuracy.toDouble())
            .put("vertical_accuracy", if (location.hasVerticalAccuracy()) location.verticalAccuracyMeters.toDouble() else JSONObject.NULL)
            .put("bearing", location.bearing.toDouble())
            .put("speed", location.speed.toDouble())
            .put("elapsedMs", (SystemClock.elapsedRealtimeNanos() - location.elapsedRealtimeNanos) / 1_000_000)
            .put("provider", location.provider ?: name)
    }

    private fun lastKnown(manager: LocationManager, provider: String): Location? = try {
        manager.getLastKnownLocation(provider)
    } catch (_: SecurityException) {
        null
    }

    @Suppress("DEPRECATION")
    override fun wifi(): JSONObject {
        val manager = context.getSystemService(WifiManager::class.java) ?: return JSONObject()
        val info = try {
            manager.connectionInfo
        } catch (_: Exception) {
            null
        } ?: return JSONObject()
        val ip = info.ipAddress
        return JSONObject()
            .put("ssid", info.ssid?.trim('"') ?: JSONObject.NULL)
            .put("bssid", info.bssid ?: JSONObject.NULL)
            .put("rssi", info.rssi)
            .put("link_speed_mbps", info.linkSpeed)
            .put("frequency_mhz", info.frequency)
            .put("ip", "%d.%d.%d.%d".format(ip and 0xff, ip shr 8 and 0xff, ip shr 16 and 0xff, ip shr 24 and 0xff))
            .put("network_id", info.networkId)
            .put("ssid_hidden", info.hiddenSSID)
            .put("supplicant_state", info.supplicantState?.toString() ?: JSONObject.NULL)
    }

    // --- camera --------------------------------------------------------------------

    @Suppress("DEPRECATION")
    override fun cameraPhoto(facing: String, into: File) {
        requirePermission("camera")
        val manager = context.getSystemService(CameraManager::class.java) ?: throw SensorUnavailable("this phone has no camera service")
        val wanted = if (facing == "front") CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
        val id = manager.cameraIdList.firstOrNull { manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == wanted }
            ?: throw SensorUnavailable("this phone has no $facing camera")
        val chars = manager.getCameraCharacteristics(id)
        val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val jpegSizes = map?.getOutputSizes(ImageFormat.JPEG)?.toList().orEmpty()
        val jpeg = jpegSizes.filter { it.width * it.height <= MAX_PIXELS }.maxByOrNull { it.width * it.height }
            ?: jpegSizes.minByOrNull { it.width * it.height } ?: Size(1920, 1080)
        val previewSizes = map?.getOutputSizes(SurfaceTexture::class.java)?.toList().orEmpty()
        val preview = previewSizes.filter { it.width * it.height <= PREVIEW_PIXELS }.maxByOrNull { it.width * it.height }
            ?: previewSizes.minByOrNull { it.width * it.height } ?: Size(1280, 720)
        val orientation = chars.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0

        val result = CompletableFuture<ByteArray>()
        val reader = ImageReader.newInstance(jpeg.width, jpeg.height, ImageFormat.JPEG, 2)
        reader.setOnImageAvailableListener({ r ->
            val image = r.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                if (!result.isDone) {
                    val buffer = image.planes[0].buffer
                    val bytes = ByteArray(buffer.remaining())
                    buffer.get(bytes)
                    result.complete(bytes)
                }
            } finally {
                image.close()
            }
        }, handler)
        // A preview nobody sees, so exposure and focus settle before the still (what a camera app does).
        val texture = SurfaceTexture(false).apply { setDefaultBufferSize(preview.width, preview.height) }
        val previewSurface = Surface(texture)
        var camera: CameraDevice? = null
        var session: CameraCaptureSession? = null

        val callback = object : CameraDevice.StateCallback() {
            override fun onOpened(device: CameraDevice) {
                camera = device
                try {
                    device.createCaptureSession(
                        listOf(previewSurface, reader.surface),
                        object : CameraCaptureSession.StateCallback() {
                            override fun onConfigured(s: CameraCaptureSession) {
                                session = s
                                try {
                                    val previewRequest = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                                        addTarget(previewSurface)
                                        set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
                                        set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                                        set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
                                    }.build()
                                    s.setRepeatingRequest(previewRequest, null, handler)
                                    handler.postDelayed({
                                        try {
                                            val still = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                                                addTarget(reader.surface)
                                                set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
                                                set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                                                set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
                                                set(CaptureRequest.JPEG_ORIENTATION, orientation)
                                            }.build()
                                            s.capture(still, null, handler)
                                        } catch (e: Exception) {
                                            result.completeExceptionally(e)
                                        }
                                    }, WARM_UP_MS)
                                } catch (e: Exception) {
                                    result.completeExceptionally(e)
                                }
                            }

                            override fun onConfigureFailed(s: CameraCaptureSession) {
                                result.completeExceptionally(SensorUnavailable("the camera refused the capture session"))
                            }
                        },
                        handler,
                    )
                } catch (e: Exception) {
                    result.completeExceptionally(e)
                }
            }

            override fun onDisconnected(device: CameraDevice) {
                result.completeExceptionally(SensorUnavailable("the camera disconnected (another app is using it?)"))
            }

            override fun onError(device: CameraDevice, error: Int) {
                result.completeExceptionally(SensorUnavailable("camera error $error"))
            }
        }
        try {
            try {
                manager.openCamera(id, callback, handler)
            } catch (_: SecurityException) {
                throw SensorUnavailable(SensorPermissions.needs("camera"))
            }
            val bytes = try {
                result.get(CAMERA_TIMEOUT_S, TimeUnit.SECONDS)
            } catch (_: TimeoutException) {
                throw SensorUnavailable("the camera produced no picture within ${CAMERA_TIMEOUT_S}s")
            } catch (e: ExecutionException) {
                throw (e.cause as? SensorUnavailable) ?: SensorUnavailable("camera failed: ${e.cause?.message ?: e.cause?.javaClass?.simpleName}")
            }
            into.parentFile?.mkdirs()
            into.writeBytes(bytes)
        } finally {
            for (step in listOf<() -> Unit>(
                { session?.stopRepeating() }, { session?.close() }, { camera?.close() },
                { reader.close() }, { previewSurface.release() }, { texture.release() },
            )) {
                try {
                    step()
                } catch (_: Exception) {
                }
            }
        }
    }

    // --- microphone -------------------------------------------------------------------

    @Suppress("DEPRECATION")
    override fun micRecord(seconds: Int, into: File) {
        requirePermission("microphone")
        into.parentFile?.mkdirs()
        val recorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) MediaRecorder(context) else MediaRecorder()
        try {
            recorder.setAudioSource(MediaRecorder.AudioSource.MIC)
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            recorder.setAudioEncodingBitRate(96_000)
            recorder.setAudioSamplingRate(44_100)
            recorder.setOutputFile(into.path)
            recorder.prepare()
            recorder.start()
        } catch (e: Exception) {
            recorder.release()
            throw SensorUnavailable("the microphone could not start (in use by another app?): ${e.message ?: e.javaClass.simpleName}")
        }
        try {
            Thread.sleep(seconds * 1000L)
            recorder.stop()
        } catch (e: Exception) {
            throw SensorUnavailable("the recording stopped early: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            recorder.release()
        }
    }

    // --- text to speech -------------------------------------------------------------

    private var tts: TextToSpeech? = null
    private var ttsReady: CompletableFuture<Int>? = null

    private fun engine(): TextToSpeech {
        val (engine, ready) = synchronized(this) {
            val current = tts
            val readiness = ttsReady
            if (current != null && readiness != null && readiness.getNow(TextToSpeech.ERROR) == TextToSpeech.SUCCESS) return current
            val fresh = CompletableFuture<Int>()
            val holder = CompletableFuture<TextToSpeech>()
            main.post { holder.complete(TextToSpeech(context) { status -> fresh.complete(status) }) }
            val created = try {
                holder.get(10, TimeUnit.SECONDS)
            } catch (_: TimeoutException) {
                throw SensorUnavailable("the text-to-speech engine did not start")
            }
            tts = created
            ttsReady = fresh
            created to fresh
        }
        val status = try {
            ready.get(10, TimeUnit.SECONDS)
        } catch (_: TimeoutException) {
            throw SensorUnavailable("the text-to-speech engine did not start")
        }
        if (status != TextToSpeech.SUCCESS) {
            synchronized(this) {
                tts = null
                ttsReady = null
            }
            throw SensorUnavailable("this phone has no working text-to-speech engine")
        }
        return engine
    }

    override fun ttsSpeak(text: String) {
        val engine = engine()
        val done = CompletableFuture<Boolean>()
        val id = "caelza-${System.nanoTime()}"
        engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}

            override fun onDone(utteranceId: String?) {
                if (utteranceId == id) done.complete(true)
            }

            @Suppress("OVERRIDE_DEPRECATION") // abstract in the base class, so it must be overridden even though deprecated
            override fun onError(utteranceId: String?) {
                if (utteranceId == id) done.complete(false)
            }

            override fun onError(utteranceId: String?, errorCode: Int) {
                if (utteranceId == id) done.complete(false)
            }
        })
        if (engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS) {
            throw SensorUnavailable("the text-to-speech engine refused to speak")
        }
        val spoken = try {
            done.get(TTS_TIMEOUT_S, TimeUnit.SECONDS)
        } catch (_: TimeoutException) {
            engine.stop()
            throw SensorUnavailable("speaking did not finish within ${TTS_TIMEOUT_S}s")
        }
        if (!spoken) throw SensorUnavailable("the text-to-speech engine reported an error")
    }

    // --- torch ---------------------------------------------------------------------------

    override fun torch(on: Boolean) {
        val manager = context.getSystemService(CameraManager::class.java) ?: throw SensorUnavailable("this phone has no camera service")
        val withFlash = manager.cameraIdList.filter { manager.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true }
        val id = withFlash.firstOrNull { manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK }
            ?: withFlash.firstOrNull() ?: throw SensorUnavailable("this phone has no flashlight")
        try {
            manager.setTorchMode(id, on)
        } catch (e: Exception) {
            throw SensorUnavailable("the flashlight is busy (the camera is in use?): ${e.message ?: e.javaClass.simpleName}")
        }
    }

    companion object {
        /** A photo for an agent, not a print: the largest JPEG size up to about 1080p. */
        const val MAX_PIXELS = 2_200_000
        const val PREVIEW_PIXELS = 1_000_000
        const val WARM_UP_MS = 900L
        const val CAMERA_TIMEOUT_S = 20L
        const val LOCATION_TIMEOUT_S = 45L
        const val TTS_TIMEOUT_S = 60L

        private val HEALTH = mapOf(
            BatteryManager.BATTERY_HEALTH_UNKNOWN to "UNKNOWN", BatteryManager.BATTERY_HEALTH_GOOD to "GOOD",
            BatteryManager.BATTERY_HEALTH_OVERHEAT to "OVERHEAT", BatteryManager.BATTERY_HEALTH_DEAD to "DEAD",
            BatteryManager.BATTERY_HEALTH_OVER_VOLTAGE to "OVER_VOLTAGE", BatteryManager.BATTERY_HEALTH_UNSPECIFIED_FAILURE to "UNSPECIFIED_FAILURE",
            BatteryManager.BATTERY_HEALTH_COLD to "COLD",
        )
        private val STATUS = mapOf(
            BatteryManager.BATTERY_STATUS_UNKNOWN to "UNKNOWN", BatteryManager.BATTERY_STATUS_CHARGING to "CHARGING",
            BatteryManager.BATTERY_STATUS_DISCHARGING to "DISCHARGING", BatteryManager.BATTERY_STATUS_NOT_CHARGING to "NOT_CHARGING",
            BatteryManager.BATTERY_STATUS_FULL to "FULL",
        )
    }
}
