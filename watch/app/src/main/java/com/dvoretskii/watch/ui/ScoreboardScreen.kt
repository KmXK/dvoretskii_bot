package com.dvoretskii.watch.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ChipDefaults
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.dvoretskii.watch.data.ActiveState
import com.dvoretskii.watch.data.ApiClient
import com.dvoretskii.watch.data.ApiException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val POLL_MS = 2500L

private val sideA = Color(0xFFF43F5E)   // rose
private val sideB = Color(0xFF38BDF8)   // sky

@Composable
fun ScoreboardScreen(api: ApiClient, onUnauthorized: () -> Unit) {
    val scope = rememberCoroutineScope()
    var state by remember { mutableStateOf<ActiveState?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    suspend fun refresh() {
        try {
            state = api.getActive()
            error = null
        } catch (e: ApiException) {
            if (e.status == 401) { onUnauthorized(); return }
            error = e.message
        } catch (e: Exception) {
            error = e.message ?: "Нет связи"
        } finally {
            loading = false
        }
    }

    // Поллинг — ловим изменения, сделанные с телефона/вебаппы.
    LaunchedEffect(Unit) {
        while (true) {
            refresh()
            delay(POLL_MS)
        }
    }

    fun act(block: suspend () -> ActiveState?) {
        if (busy) return
        busy = true
        scope.launch {
            try {
                val updated = block()
                if (updated != null) state = updated
                error = null
            } catch (e: ApiException) {
                if (e.status == 401) onUnauthorized() else error = e.message
            } catch (e: Exception) {
                error = e.message ?: "Ошибка"
            } finally {
                busy = false
            }
        }
    }

    val s = state
    when {
        loading && s == null -> Box(Modifier.fillMaxSize(), Alignment.Center) {
            CircularProgressIndicator()
        }
        s == null -> NoActiveSession(error)
        else -> Scoreboard(
            s = s,
            busy = busy,
            onPointA = { act { api.addPoint(s.sessionId, "a") } },
            onPointB = { act { api.addPoint(s.sessionId, "b") } },
            onUndo = { act { api.undoPoint(s.sessionId) } },
        )
    }
}

@Composable
private fun NoActiveSession(error: String?) {
    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("Нет активной сессии", style = MaterialTheme.typography.title3, textAlign = TextAlign.Center)
        Text(
            "Создай сессию в вебаппе — счёт появится здесь.",
            style = MaterialTheme.typography.caption2,
            color = MaterialTheme.colors.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 6.dp),
        )
        error?.let {
            Text(it, style = MaterialTheme.typography.caption3, color = MaterialTheme.colors.error,
                textAlign = TextAlign.Center, modifier = Modifier.padding(top = 8.dp))
        }
    }
}

@Composable
private fun Scoreboard(
    s: ActiveState,
    busy: Boolean,
    onPointA: () -> Unit,
    onPointB: () -> Unit,
    onUndo: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 8.dp, vertical = 18.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp, Alignment.CenterVertically),
    ) {
        // Имена + счёт по партиям
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
            ServerDot(active = s.currentServer == "a", color = sideA)
            Text(
                text = "${s.playerA}  ${s.winsA}:${s.winsB}  ${s.playerB}",
                style = MaterialTheme.typography.caption2,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(horizontal = 4.dp),
            )
            ServerDot(active = s.currentServer == "b", color = sideB)
        }

        // Крупный счёт текущей партии
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("${s.scoreA}", fontSize = 40.sp, fontWeight = FontWeight.Black, color = sideA)
            Text(" : ", fontSize = 30.sp, color = MaterialTheme.colors.onSurfaceVariant)
            Text("${s.scoreB}", fontSize = 40.sp, fontWeight = FontWeight.Black, color = sideB)
        }

        // Две зоны +1
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            PointButton("+1", sideA, enabled = !busy, modifier = Modifier.weight(1f), onClick = onPointA)
            PointButton("+1", sideB, enabled = !busy, modifier = Modifier.weight(1f), onClick = onPointB)
        }

        Chip(
            label = { Text("↩ Отменить очко") },
            onClick = onUndo,
            enabled = !busy,
            colors = ChipDefaults.secondaryChipColors(),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun PointButton(
    label: String,
    color: Color,
    enabled: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        colors = ButtonDefaults.buttonColors(backgroundColor = color),
        modifier = modifier,
    ) {
        Text(label, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
    }
}

@Composable
private fun ServerDot(active: Boolean, color: Color) {
    Box(
        modifier = Modifier
            .size(8.dp)
            .clip(androidx.compose.foundation.shape.CircleShape)
            .then(
                if (active) Modifier.background(color) else Modifier.background(Color.Transparent)
            )
    )
}
