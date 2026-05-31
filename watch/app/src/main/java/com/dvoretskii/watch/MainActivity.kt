package com.dvoretskii.watch

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.TimeText
import com.dvoretskii.watch.data.ApiClient
import com.dvoretskii.watch.data.Prefs
import com.dvoretskii.watch.ui.PairScreen
import com.dvoretskii.watch.ui.ScoreboardScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = Prefs(applicationContext)
        val api = ApiClient(prefs)
        setContent { WatchApp(prefs, api) }
    }
}

@Composable
private fun WatchApp(prefs: Prefs, api: ApiClient) {
    var paired by remember { mutableStateOf(prefs.isPaired) }

    MaterialTheme {
        Scaffold(timeText = { TimeText() }) {
            if (!paired) {
                PairScreen(api = api, onPaired = { paired = true })
            } else {
                ScoreboardScreen(
                    api = api,
                    onUnauthorized = {
                        prefs.clear()
                        paired = false
                    },
                )
            }
        }
    }
}
