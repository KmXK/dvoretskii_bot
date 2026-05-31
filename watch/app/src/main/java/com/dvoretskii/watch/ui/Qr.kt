package com.dvoretskii.watch.ui

import android.graphics.Bitmap
import android.graphics.Color as AColor
import androidx.compose.foundation.Image
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter

/** Рендер QR-кода из строки. Чёрное на белом — чтобы телефон уверенно сканировал. */
@Composable
fun QrImage(content: String, modifier: Modifier = Modifier, sizePx: Int = 360) {
    val bmp = remember(content, sizePx) { qrBitmap(content, sizePx) }
    if (bmp != null) {
        Image(
            bitmap = bmp.asImageBitmap(),
            contentDescription = "QR",
            modifier = modifier,
            contentScale = ContentScale.Fit,
        )
    }
}

private fun qrBitmap(content: String, size: Int): Bitmap? = try {
    val hints = mapOf(EncodeHintType.MARGIN to 1)
    val matrix = QRCodeWriter().encode(content, BarcodeFormat.QR_CODE, size, size, hints)
    val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.RGB_565)
    for (x in 0 until size) {
        for (y in 0 until size) {
            bmp.setPixel(x, y, if (matrix[x, y]) AColor.BLACK else AColor.WHITE)
        }
    }
    bmp
} catch (e: Exception) {
    null
}
