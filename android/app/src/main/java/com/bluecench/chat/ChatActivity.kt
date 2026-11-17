package com.bluecench.chat

import android.annotation.SuppressLint
import android.content.ContentValues
import android.graphics.Color
import android.net.Uri
import android.net.http.SslError
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.webkit.CookieManager
import android.webkit.SslErrorHandler
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import java.net.URL
import javax.net.ssl.HttpsURLConnection
import kotlin.concurrent.thread

/** Shows the Blue Cench Chat app served by the PC, with its certificate pinned. */
class ChatActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var host: String
    private var port = 8765
    private var expectedFp = ""
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    private val pickFiles = registerForActivityResult(ActivityResultContracts.GetMultipleContents()) { uris ->
        fileCallback?.onReceiveValue(uris.toTypedArray())
        fileCallback = null
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        host = intent.getStringExtra("host") ?: run { finish(); return }
        port = intent.getIntExtra("port", 8765)
        expectedFp = intent.getStringExtra("fp").orEmpty().ifEmpty { Trust.saved(this, host).orEmpty() }

        web = WebView(this)
        web.setBackgroundColor(Color.parseColor("#070B14"))
        setContentView(web)
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = true
            mediaPlaybackRequiresUserGesture = true
            setSupportZoom(false)
        }

        web.webViewClient = object : WebViewClient() {
            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
                val cert = error.certificate.x509Certificate
                val fp = if (cert != null) Trust.fingerprint(cert) else ""
                when {
                    fp.isNotEmpty() && fp.equals(expectedFp, ignoreCase = true) -> handler.proceed()
                    fp.isNotEmpty() && expectedFp.isEmpty() -> askToTrust(fp, handler)
                    else -> {
                        handler.cancel()
                        AlertDialog.Builder(this@ChatActivity)
                            .setTitle("Security warning")
                            .setMessage("This device did not present your PC's certificate. The connection was " +
                                "blocked.\n\nExpected: $expectedFp\nReceived: $fp")
                            .setPositiveButton("OK") { _, _ -> finish() }
                            .show()
                    }
                }
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // Stay inside the Blue Cench Chat page; never follow links elsewhere.
                return request.url.host != host
            }
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView,
                callback: ValueCallback<Array<Uri>>,
                params: FileChooserParams,
            ): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                pickFiles.launch("*/*")
                return true
            }
        }

        web.setDownloadListener { url, _, contentDisposition, mimeType, _ ->
            download(url, URLUtil.guessFileName(url, contentDisposition, mimeType), mimeType)
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
            }
        })

        if (savedInstanceState != null) web.restoreState(savedInstanceState)
        else web.loadUrl("https://$host:$port/")
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    private fun askToTrust(fp: String, handler: SslErrorHandler) {
        AlertDialog.Builder(this)
            .setTitle("Is this your PC?")
            .setMessage("Compare this fingerprint with the one shown on the PC under Phones & Tablets:\n\n$fp")
            .setPositiveButton("They match") { _, _ ->
                expectedFp = fp
                Trust.save(this, host, fp)
                handler.proceed()
            }
            .setNegativeButton("Cancel") { _, _ -> handler.cancel(); finish() }
            .setCancelable(false)
            .show()
    }

    /** Saves a received file to the phone's Downloads folder over the pinned connection. */
    private fun download(url: String, name: String, mime: String?) {
        val fp = expectedFp
        if (fp.isEmpty()) return
        Toast.makeText(this, "Saving $name…", Toast.LENGTH_SHORT).show()
        val cookie = CookieManager.getInstance().getCookie(url)
        thread {
            try {
                val conn = URL(url).openConnection() as HttpsURLConnection
                conn.sslSocketFactory = Trust.pinnedSocketFactory(fp)
                conn.hostnameVerifier = Trust.pinnedHostnames
                if (cookie != null) conn.setRequestProperty("Cookie", cookie)
                conn.connect()
                if (conn.responseCode != 200) throw Exception("PC answered ${conn.responseCode}")
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, name)
                    put(MediaStore.Downloads.MIME_TYPE, mime ?: "application/octet-stream")
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Blue Cench Chat")
                }
                val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: throw Exception("cannot create file")
                conn.inputStream.use { input ->
                    contentResolver.openOutputStream(uri)!!.use { out -> input.copyTo(out) }
                }
                runOnUiThread {
                    Toast.makeText(this, "Saved to Downloads/Blue Cench Chat/$name", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                runOnUiThread { Toast.makeText(this, "Download failed: ${e.message}", Toast.LENGTH_LONG).show() }
            }
        }
    }
}
