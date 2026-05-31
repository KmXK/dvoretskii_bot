package com.dvoretskii.watch.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
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
    var sessions by remember { mutableStateOf<List<ActiveState>>(emptyList()) }
    var selectedId by remember { mutableStateOf<Int?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    suspend fun refresh() {
        try {
            sessions = api.getActiveSessions()
            error = null
            // авто-выбор единственной; сброс, если выбранная исчезла
            if (sessions.size == 1) selectedId = sessions[0].sessionId
            else if (selectedId != null && sessions.none { it.sessionId == selectedId }) selectedId = null
        } catch (e: ApiException) {
            if (e.status == 401) { onUnauthorized(); return }
            error = e.message
        } catch (e: Exception) {
            error = e.message ?: "Нет связи"
        } finally {
            loading = false
        }
    }

    // Поллинг — ловим изменения, сделанные с телефона/вебаппы/других часов.
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
                if (updated != null) {
                    sessions = sessions.map { if (it.sessionId == updated.sessionId) updated else it }
                }
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

    val selected = sessions.firstOrNull { it.sessionId == selectedId }
    when {
        loading && sessions.isEmpty() -> Box(Modifier.fillMaxSize(), Alignment.Center) {
            CircularProgressIndicator()
        }
        sessions.isEmpty() -> NoActiveSession(error)
        selected == null -> SessionPicker(sessions = sessions, onPick = { selectedId = it })
        else -> Scoreboard(
            s = selected,
            canSwitch = sessions.size > 1,
            busy = busy,
            onPointA = { act { api.addPoint(selected.sessionId, "a") } },
            onPointB = { act { api.addPoint(selected.sessionId, "b") } },
            onUndo = { act { api.undoPoint(selected.sessionId) } },
            onSwitch = { selectedId = null },
        )
    }
}

@Composable
private fun SessionPicker(sessions: List<ActiveState>, onPick: (Int) -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 26.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text("Какая сессия?", style = MaterialTheme.typography.title3, textAlign = TextAlign.Center)
        sessions.forEach { s ->
            Chip(
                modifier = Modifier.fillMaxWidth(),
                onClick = { onPick(s.sessionId) },
                colors = ChipDefaults.secondaryChipColors(),
                label = {
                    Text(
                        "${s.playerA} ${s.winsA}:${s.winsB} ${s.playerB}",
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.fillMaxWidth(),
                        textAlign = TextAlign.Center,
                    )
                },
            )
        }
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
    canSwitch: Boolean,
    busy: Boolean,
    onPointA: () -> Unit,
    onPointB: () -> Unit,
    onUndo: () -> Unit,
    onSwitch: () -> Unit,
) {
    // Горизонтальные поля побольше — на круглом экране края обрезаются.
    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 26.dp, vertical = 14.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(3.dp, Alignment.CenterVertically),
    ) {
        if (canSwitch) {
            Text(
                "▾ сменить сессию",
                style = MaterialTheme.typography.caption3,
                color = MaterialTheme.colors.onSurfaceVariant,
                modifier = Modifier.clickable(enabled = !busy, onClick = onSwitch),
            )
        }
        // Имена (по центру, с эллипсисом) — без краевых элементов, чтобы не резалось.
        Text(
            text = "${s.playerA} ${s.winsA}:${s.winsB} ${s.playerB}",
            style = MaterialTheme.typography.caption2,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )

        // Крупный счёт текущей партии; подача — цветная точка под подающей стороной.
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("${s.scoreA}", fontSize = 38.sp, fontWeight = FontWeight.Black, color = sideA)
            Text(" : ", fontSize = 26.sp, color = MaterialTheme.colors.onSurfaceVariant)
            Text("${s.scoreB}", fontSize = 38.sp, fontWeight = FontWeight.Black, color = sideB)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(48.dp)) {
            ServerDot(active = s.currentServer == "a", color = sideA)
            ServerDot(active = s.currentServer == "b", color = sideB)
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
            label = { Text("↩ Отменить", modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center) },
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
