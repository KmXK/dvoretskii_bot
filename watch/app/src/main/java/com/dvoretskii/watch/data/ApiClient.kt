package com.dvoretskii.watch.data

import com.dvoretskii.watch.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Ошибка уровня приложения (HTTP не-2xx с понятным текстом). */
class ApiException(val status: Int, message: String) : IOException(message)

/**
 * Тонкий REST-клиент к боту. Привязка по коду → bearer-токен; дальше теннисные
 * ручки бьются с заголовком Authorization. Все вызовы — suspend, уходят на IO.
 */
class ApiClient(private val prefs: Prefs) {

    private val baseUrl = BuildConfig.BOT_BASE_URL.trimEnd('/')
    private val json = "application/json; charset=utf-8".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    /** Обменять код привязки на токен. Токен сохраняется в Prefs. */
    suspend fun pair(code: String, deviceName: String): PairResult = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("code", code)
            .put("device_name", deviceName)
            .toString()
            .toRequestBody(json)
        val req = Request.Builder()
            .url("$baseUrl/api/watch/pair/claim")
            .post(body)
            .build()
        http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ApiException(resp.code, errorOf(text, "код неверный или истёк"))
            val obj = JSONObject(text)
            val token = obj.optString("token")
            if (token.isBlank()) throw ApiException(resp.code, "сервер не вернул токен")
            prefs.token = token
            val userName = obj.optString("user_name", "")
            prefs.userName = userName
            PairResult(userName = userName)
        }
    }

    /** Текущая активная сессия (или null, если её нет). */
    suspend fun getActive(): ActiveState? = withContext(Dispatchers.IO) {
        val req = authed(Request.Builder().url("$baseUrl/api/tennis/active").get()).build()
        http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (resp.code == 401) throw ApiException(401, "unauthorized")
            if (!resp.isSuccessful) throw ApiException(resp.code, errorOf(text, "ошибка ${resp.code}"))
            val obj = JSONObject(text)
            if (!obj.optBoolean("active", false)) return@use null
            parseState(obj.getJSONObject("state"))
        }
    }

    suspend fun addPoint(sessionId: Int, side: String): ActiveState? = withContext(Dispatchers.IO) {
        val body = JSONObject().put("side", side).toString().toRequestBody(json)
        val req = authed(
            Request.Builder().url("$baseUrl/api/tennis/sessions/$sessionId/point").post(body)
        ).build()
        postForState(req)
    }

    suspend fun undoPoint(sessionId: Int): ActiveState? = withContext(Dispatchers.IO) {
        val empty = "".toRequestBody(json)
        val req = authed(
            Request.Builder().url("$baseUrl/api/tennis/sessions/$sessionId/undo_point").post(empty)
        ).build()
        postForState(req)
    }

    private fun postForState(req: Request): ActiveState? {
        http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (resp.code == 401) throw ApiException(401, "unauthorized")
            if (!resp.isSuccessful) throw ApiException(resp.code, errorOf(text, "ошибка ${resp.code}"))
            val obj = JSONObject(text)
            val state = obj.optJSONObject("state") ?: return null
            return parseState(state)
        }
    }

    private fun authed(builder: Request.Builder): Request.Builder {
        prefs.token?.let { builder.header("Authorization", "Bearer $it") }
        return builder
    }

    private fun parseState(s: JSONObject): ActiveState {
        val wins = s.optJSONArray("wins")
        val score = s.optJSONArray("current_score")
        return ActiveState(
            sessionId = s.getInt("id"),
            sport = s.optString("sport", "table_tennis"),
            playerA = s.optString("player_a_name", "A"),
            playerB = s.optString("player_b_name", "B"),
            winsA = wins?.optInt(0, 0) ?: 0,
            winsB = wins?.optInt(1, 0) ?: 0,
            scoreA = score?.optInt(0, 0) ?: 0,
            scoreB = score?.optInt(1, 0) ?: 0,
            currentServer = s.optString("current_server").ifBlank { null },
        )
    }

    private fun errorOf(body: String, fallback: String): String = try {
        JSONObject(body).optString("error", fallback)
    } catch (_: Exception) {
        fallback
    }
}
