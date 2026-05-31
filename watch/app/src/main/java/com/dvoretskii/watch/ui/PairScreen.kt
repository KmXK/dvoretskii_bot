package com.dvoretskii.watch.ui

import android.app.Activity
import android.content.Intent
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.app.RemoteInput
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ChipDefaults
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import androidx.wear.input.RemoteInputIntentHelper
import com.dvoretskii.watch.data.ApiClient
import kotlinx.coroutines.launch

private const val KEY_CODE = "code"

@Composable
fun PairScreen(api: ApiClient, onPaired: () -> Unit) {
    val scope = rememberCoroutineScope()
    var code by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val deviceName = remember { Build.MODEL?.takeIf { it.isNotBlank() } ?: "Часы" }

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val text = RemoteInput.getResultsFromIntent(result.data)
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
        busy = true
        error = null
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
            .padding(horizontal = 12.dp, vertical = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterVertically),
    ) {
        Text(
            text = "Привязка к боту",
            style = MaterialTheme.typography.title3,
            textAlign = TextAlign.Center,
        )
        Text(
            text = "Открой «Привязать часы» в вебаппе и введи показанный код.",
            style = MaterialTheme.typography.caption2,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colors.onSurfaceVariant,
        )

        Chip(
            modifier = Modifier.fillMaxWidth(),
            label = {
                Text(
                    text = if (code.isBlank()) "Ввести код" else "Код: $code",
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            onClick = ::launchInput,
            colors = ChipDefaults.secondaryChipColors(),
        )

        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = code.isNotBlank() && !busy,
            onClick = ::submit,
        ) {
            Text(if (busy) "Привязываем…" else "Привязать")
        }

        error?.let {
            Text(
                text = it,
                style = MaterialTheme.typography.caption2,
                color = MaterialTheme.colors.error,
                textAlign = TextAlign.Center,
            )
        }
    }
}
