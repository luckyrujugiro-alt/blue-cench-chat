package com.bluecench.chat

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.wifi.WifiManager
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketTimeoutException
import kotlin.concurrent.thread

/**
 * Finds Blue Cench Chat PCs on the same Wi-Fi / hotspot by listening for the presence
 * beacons the desktop app broadcasts (UDP 47820). No link or QR code needed.
 */
class MainActivity : AppCompatActivity() {

    data class Pc(val name: String, val uid: String, val ip: String, val port: Int, val fp: String, var seen: Long)

    private val pcs = linkedMapOf<String, Pc>()
    private lateinit var list: LinearLayout
    private lateinit var status: TextView
    @Volatile private var running = false
    private var lock: WifiManager.MulticastLock? = null
    private var autoOpened = false

    private val bg = Color.parseColor("#070B14")
    private val card = Color.parseColor("#0E1526")
    private val textColor = Color.parseColor("#E7EEF9")
    private val muted = Color.parseColor("#8C9AB6")
    private val blue = Color.parseColor("#2F7BFF")

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(bg)
            setPadding(dp(20), dp(36), dp(20), dp(20))
        }
        root.addView(ImageView(this).apply {
            setImageResource(R.mipmap.ic_launcher)
            layoutParams = LinearLayout.LayoutParams(dp(64), dp(64))
        })
        root.addView(TextView(this).apply {
            setText(R.string.app_name)
            setTextColor(textColor)
            textSize = 26f
            typeface = Typeface.DEFAULT_BOLD
            setPadding(0, dp(12), 0, dp(4))
        })
        status = TextView(this).apply {
            setTextColor(muted)
            textSize = 15f
            text = "Looking for your PC on this Wi-Fi…"
        }
        root.addView(status)
        root.addView(ProgressBar(this).apply {
            isIndeterminate = true
            layoutParams = LinearLayout.LayoutParams(dp(28), dp(28)).apply { topMargin = dp(12) }
        })
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(ScrollView(this).apply {
            addView(list)
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
                .apply { topMargin = dp(16) }
        })
        root.addView(TextView(this).apply {
            setTextColor(muted)
            textSize = 13f
            text = "On the PC: open Blue Cench Chat → Phones & Tablets → turn on “Allow phones and tablets”. " +
                "This phone must be on the same Wi-Fi as the PC, or on the PC's Mobile hotspot."
            setPadding(0, dp(8), 0, dp(10))
        })
        root.addView(Button(this).apply {
            text = "Enter PC address instead"
            setOnClickListener { manualEntry() }
        })
        setContentView(root)
        render()
    }

    override fun onResume() {
        super.onResume()
        startListening()
    }

    override fun onPause() {
        super.onPause()
        running = false
        lock?.let { if (it.isHeld) it.release() }
    }

    private fun startListening() {
        if (running) return
        running = true
        val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        lock = wifi.createMulticastLock("bluecench").apply { setReferenceCounted(false); acquire() }
        thread(isDaemon = true, name = "beacons") {
            try {
                DatagramSocket(null).use { sock ->
                    sock.reuseAddress = true
                    sock.broadcast = true
                    sock.soTimeout = 1000
                    sock.bind(InetSocketAddress(47820))
                    val buf = ByteArray(2048)
                    while (running) {
                        try {
                            val pkt = DatagramPacket(buf, buf.size)
                            sock.receive(pkt)
                            val msg = JSONObject(String(pkt.data, 0, pkt.length, Charsets.UTF_8))
                            val web = msg.optInt("web", 0)
                            if (msg.optInt("nx", 0) != 1 || web <= 0) continue
                            val ip = pkt.address.hostAddress ?: continue
                            val uid = msg.optString("uid")
                            val pc = Pc(msg.optString("name", "Blue Cench Chat PC"), uid, ip, web,
                                msg.optString("fp"), System.currentTimeMillis())
                            runOnUiThread { pcs[uid] = pc; render() }
                        } catch (_: SocketTimeoutException) {
                            runOnUiThread { prune() }
                        } catch (_: Exception) {
                        }
                    }
                }
            } catch (e: Exception) {
                runOnUiThread { status.text = "Can't listen on Wi-Fi: ${e.message}" }
            }
        }
    }

    private fun prune() {
        val now = System.currentTimeMillis()
        if (pcs.values.removeAll { now - it.seen > 12000 }) render()
    }

    private fun render() {
        list.removeAllViews()
        status.text = if (pcs.isEmpty()) "Looking for your PC on this Wi-Fi…"
        else "Found ${pcs.size} PC${if (pcs.size == 1) "" else "s"} — tap to open"
        val last = getSharedPreferences("app", MODE_PRIVATE).getString("last_uid", null)
        for (pc in pcs.values) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(16), dp(14), dp(16), dp(14))
                background = GradientDrawable().apply { setColor(card); cornerRadius = dp(14).toFloat() }
                layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(10) }
                isClickable = true
                setOnClickListener { open(pc.name, pc.uid, pc.ip, pc.port, pc.fp) }
            }
            row.addView(TextView(this).apply {
                text = pc.name; setTextColor(textColor); textSize = 17f; typeface = Typeface.DEFAULT_BOLD
            })
            row.addView(TextView(this).apply {
                text = "${pc.ip}  ·  ${pc.uid}"; setTextColor(muted); textSize = 13f
            })
            list.addView(row)
            // Re-open the PC used last time automatically.
            if (!autoOpened && pc.uid == last) {
                autoOpened = true
                open(pc.name, pc.uid, pc.ip, pc.port, pc.fp)
            }
        }
    }

    private fun open(name: String, uid: String, ip: String, port: Int, fp: String) {
        getSharedPreferences("app", MODE_PRIVATE).edit().putString("last_uid", uid).apply()
        startActivity(Intent(this, ChatActivity::class.java)
            .putExtra("name", name).putExtra("host", ip).putExtra("port", port).putExtra("fp", fp))
    }

    private fun manualEntry() {
        val input = EditText(this).apply {
            hint = "192.168.137.1:8765"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setText(getSharedPreferences("app", MODE_PRIVATE).getString("manual", ""))
        }
        AlertDialog.Builder(this)
            .setTitle("PC address")
            .setMessage("Shown on the PC under Phones & Tablets.")
            .setView(input)
            .setPositiveButton("Open") { _, _ ->
                val raw = input.text.toString().trim().removePrefix("https://").removePrefix("http://").trimEnd('/')
                val host = raw.substringBefore(":")
                val port = raw.substringAfter(":", "8765").toIntOrNull() ?: 8765
                if (host.isNotEmpty()) {
                    getSharedPreferences("app", MODE_PRIVATE).edit().putString("manual", raw).apply()
                    open(host, "manual:$host", host, port, "")
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }
}
