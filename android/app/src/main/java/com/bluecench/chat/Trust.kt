package com.bluecench.chat

import android.content.Context
import java.security.MessageDigest
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * The PC creates its own HTTPS certificate, so no public authority vouches for it.
 * Instead we *pin* it: a connection is accepted only when the certificate's SHA-256
 * fingerprint equals the one the PC announced on the local network (or that the user
 * approved once). The format matches the desktop app: first 16 bytes, "AB:CD:...".
 */
object Trust {
    fun fingerprint(cert: X509Certificate): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(cert.encoded)
        return digest.take(16).joinToString(":") { "%02X".format(it) }
    }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("trust", Context.MODE_PRIVATE)

    fun saved(ctx: Context, host: String): String? = prefs(ctx).getString("fp:$host", null)

    fun save(ctx: Context, host: String, fp: String) {
        prefs(ctx).edit().putString("fp:$host", fp).apply()
    }

    /** Socket factory that only trusts a certificate with the given fingerprint. */
    fun pinnedSocketFactory(expected: String): SSLSocketFactory {
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {
                throw java.security.cert.CertificateException("client certificates not used")
            }

            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                if (chain.isEmpty() || !fingerprint(chain[0]).equals(expected, ignoreCase = true)) {
                    throw java.security.cert.CertificateException("certificate does not match this PC")
                }
            }

            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
        }
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf<TrustManager>(tm), null)
        return ctx.socketFactory
    }

    // The certificate is pinned above, so the host name (an IP address) is not what
    // establishes trust.
    val pinnedHostnames = HostnameVerifier { _, _ -> true }
}
