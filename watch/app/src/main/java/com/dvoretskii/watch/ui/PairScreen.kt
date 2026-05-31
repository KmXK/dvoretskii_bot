package com.dvoretskii.watch.ui

import android.app.Activity
import android.content.Intent
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import android.app.RemoteInput
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ChipDefaults
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import androidx.wear.input.RemoteInputIntentHelper
import com.dvoretskii.watch.data.ApiClient
import com.dvoretskii.watch.data.ApiException
import com.dvoretskii.watch.data.PairStart
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val KEY_CODE = "code"

@Composable
fun PairScreen(api: ApiClient, onPaired: () -> Unit) {
    var manual by remember { mutableStateOf(false) }
    if (manual) {
        CodeEntry(api = api, onPaired = onPaired, onBack = { manual = false })
    } else {
        QrPairing(api = api, onPaired = onPaired, onManual = { manual = true })
    }
}

// ── QR-привязка (основной путь): часы показывают QR, телефон сканирует ─────────

@Composable
private fun QrPairing(api: ApiClient, onPaired: () -> Unit, onManual: () -> Unit) {
    var start by remember { mutableStateOf<PairStart?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reloadKey by remember { mutableStateOf(0) }
    val deviceName = remember { Build.MODEL?.takeIf { it.isNotBlank() } ?: "Часы" }

    // Стартуем (и перезапускаем по reloadKey/истечению) генерацию кода.
    LaunchedEffect(reloadKey) {
        start = null
        error = null
        try {
            start = api.deviceStart(deviceName)
        } catch (e: Exception) {
            error = e.message ?: "Нет связи с ботом"
        }
    }

    // Поллинг статуса, пока показан конкретный код.
    val s = start
    if (s != null) {
        LaunchedEffect(s.pairId) {
            while (true) {
                delay(2000)
                try {
                    if (api.devicePoll(s.pairId, s.secret)) { onPaired(); break }
                } catch (e: ApiException) {
                    if (e.status == 404) { reloadKey++; break }   // код истёк — новый
                } catch (_: Exception) { /* сетевой сбой — пробуем ещё */ }
            }
        }
    }

    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterVertically),
        ) {
            when {
                error != null -> {
                    Text("Не удалось начать привязку", style = MaterialTheme.typography.title3, textAlign = TextAlign.Center)
                    Text(error!!, style = MaterialTheme.typography.caption2, color = MaterialTheme.colors.error, textAlign = TextAlign.Center)
                    Button(onClick = { reloadKey++ }) { Text("Повторить") }
                }
                s == null -> CircularProgressIndicator()
                else -> {
                    Text(
                        "Отсканируй телефоном",
                        style = MaterialTheme.typography.caption1,
                        textAlign = TextAlign.Center,
                    )
                    // Белая «карточка» с QR — для надёжного скана на тёмной теме.
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(12.dp))
                            .background(Color.White)
                            .padding(8.dp),
                    ) {
                        QrImage(content = s.deepLink, modifier = Modifier.size(120.dp))
                    }
                    Text(
                        "Откроется бот → подтверди привязку",
                        style = MaterialTheme.typography.caption3,
                        color = MaterialTheme.colors.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                    )
                    Chip(
                        label = { Text("Ввести код вручную", modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center) },
                        onClick = onManual,
                        colors = ChipDefaults.secondaryChipColors(),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }
    }
}

// ── Ручной ввод кода (фолбэк): код из вебаппы вводится на часах ───────────────

@Composable
private fun CodeEntry(api: ApiClient, onPaired: () -> Unit, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var code by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val deviceName = remember { Build.MODEL?.takeIf { it.isNotBlank() } ?: "Часы" }

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val text = result.data
                ?.let { RemoteInput.getResultsFromIntent(it) }
                ?.getCharSequence(KEY_CODE)?.toString().orEmpty()
            code = text.uppercase().filter { it.isLetterOrDigit() }
        }
    }

    fun launchInput() {
        val remoteInputs = listOf(
            RemoteInput.Builder(KEY_CODE).setLabel("Код привязки").build()
        )
        val intent: Intent = RemoteInputIntentHelper.createActionRemoteInputIntent()
        RemoteInputIntentHelper.putRemoteInputsExtra(intent, remoteInputs)
        launcher.launch(intent)
    }

    fun submit() {
        if (code.isBlank() || busy) return
        busy = true; error = null
        scope.launch {
            try {
                api.pair(code, deviceName)
                onPaired()
            } catch (e: Exception) {
                error = e.message ?: "Не удалось привязать"
            } finally {
                busy = false
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterVertically),
    ) {
        Text("Код из вебаппы", style = MaterialTheme.typography.title3, textAlign = TextAlign.Center)
        Chip(
            modifier = Modifier.fillMaxWidth(),
            label = {
                Text(
                    if (code.isBlank()) "Ввести код" else code,
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.Center,
                )
            },
            onClick = ::launchInput,
            colors = ChipDefaults.secondaryChipColors(),
        )
        Button(modifier = Modifier.fillMaxWidth(), enabled = code.isNotBlank() && !busy, onClick = ::submit) {
            Text(if (busy) "Привязываем…" else "Привязать")
        }
        error?.let {
            Text(it, style = MaterialTheme.typography.caption2, color = MaterialTheme.colors.error, textAlign = TextAlign.Center)
        }
        Chip(
            label = { Text("← к QR", modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center) },
            onClick = onBack,
            colors = ChipDefaults.secondaryChipColors(),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}
