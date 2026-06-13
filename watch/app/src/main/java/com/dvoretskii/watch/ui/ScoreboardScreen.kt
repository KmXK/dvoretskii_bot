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
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
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
    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.SpaceBetween,
    ) {
        // Session-switch link — only when multiple sessions exist; no wins row here
        if (canSwitch) {
            Box(
                modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "▾ сменить",
                    style = MaterialTheme.typography.caption3,
                    color = MaterialTheme.colors.onSurfaceVariant,
                    modifier = Modifier.clickable(enabled = !busy, onClick = onSwitch),
                )
            }
        }

        // Split tap zones — wins badge is inside each half corner
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .padding(horizontal = 6.dp, vertical = if (canSwitch) 2.dp else 10.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            HalfButton(
                score = "${s.scoreA}",
                name = s.playerA,
                wins = s.winsA,
                color = sideA,
                serving = s.currentServer == "a",
                enabled = !busy,
                modifier = Modifier.weight(1f).fillMaxHeight(),
                onClick = onPointA,
            )
            HalfButton(
                score = "${s.scoreB}",
                name = s.playerB,
                wins = s.winsB,
                color = sideB,
                serving = s.currentServer == "b",
                enabled = !busy,
                modifier = Modifier.weight(1f).fillMaxHeight(),
                onClick = onPointB,
            )
        }

        // Undo at bottom
        Chip(
            label = { Text("↩ Отменить", modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center) },
            onClick = onUndo,
            enabled = !busy,
            colors = ChipDefaults.secondaryChipColors(),
            modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp),
        )
    }
}

@Composable
private fun HalfButton(
    score: String,
    name: String,
    wins: Int,
    color: Color,
    serving: Boolean,
    enabled: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .background(color.copy(alpha = if (enabled) 0.9f else 0.5f))
            .clickable(enabled = enabled, onClick = onClick),
    ) {
        // Wins badge — top corner (overlaid)
        Text(
            "$wins",
            fontSize = 14.sp,
            fontWeight = FontWeight.Black,
            color = Color.White.copy(alpha = 0.45f),
            modifier = Modifier.align(Alignment.TopCenter).padding(top = 6.dp),
        )

        // Main content centred
        Column(
            modifier = Modifier.align(Alignment.Center),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            if (serving) {
                Box(
                    modifier = Modifier
                        .padding(bottom = 4.dp)
                        .size(7.dp)
                        .clip(CircleShape)
                        .background(Color.White.copy(alpha = 0.9f))
                )
            }
            Text(
                score,
                fontSize = 52.sp,
                fontWeight = FontWeight.Black,
                color = Color.White,
                textAlign = TextAlign.Center,
            )
            Text(
                name,
                style = MaterialTheme.typography.caption2,
                color = Color.White.copy(alpha = 0.65f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 6.dp),
            )
        }
    }
}
