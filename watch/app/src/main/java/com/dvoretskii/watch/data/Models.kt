package com.dvoretskii.watch.data

/** Лайв-состояние активной сессии — то, что отдаёт GET /api/tennis/active. */
data class ActiveState(
    val sessionId: Int,
    val sport: String,
    val playerA: String,
    val playerB: String,
    val winsA: Int,
    val winsB: Int,
    val scoreA: Int,
    val scoreB: Int,
    /** Кто подаёт в текущем розыгрыше: "a" | "b" | null. */
    val currentServer: String?,
)

/** Результат привязки по коду. */
data class PairResult(
    val userName: String,
)
