package com.dvoretskii.watch.data

import android.content.Context

/** Простое хранилище bearer-токена устройства и имени привязанного юзера. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("dvoretskii_watch", Context.MODE_PRIVATE)

    var token: String?
        get() = sp.getString(KEY_TOKEN, null)
        set(value) = sp.edit().apply {
            if (value == null) remove(KEY_TOKEN) else putString(KEY_TOKEN, value)
        }.apply()

    var userName: String?
        get() = sp.getString(KEY_USER_NAME, null)
        set(value) = sp.edit().putString(KEY_USER_NAME, value).apply()

    val isPaired: Boolean get() = !token.isNullOrBlank()

    fun clear() = sp.edit().clear().apply()

    private companion object {
        const val KEY_TOKEN = "token"
        const val KEY_USER_NAME = "user_name"
    }
}
