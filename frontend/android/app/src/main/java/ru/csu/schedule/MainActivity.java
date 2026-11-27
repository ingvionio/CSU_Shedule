package ru.csu.schedule;

import android.os.Bundle;
import android.os.SystemClock;
import android.webkit.WebView;
import androidx.core.splashscreen.SplashScreen;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.WebViewListener;

public class MainActivity extends BridgeActivity {
    private boolean firstFrameReady;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        SplashScreen splash = SplashScreen.installSplashScreen(this);
        long deadline = SystemClock.uptimeMillis() + 5000;
        // Между заставкой и готовой страницей WebView может показать белый фон.
        bridgeBuilder.addWebViewListener(new WebViewListener() {
            @Override
            public void onPageLoaded(WebView webView) {
                if (firstFrameReady) return;
                webView.postVisualStateCallback(0, new WebView.VisualStateCallback() {
                    @Override
                    public void onComplete(long requestId) {
                        firstFrameReady = true;
                    }
                });
            }
        });
        super.onCreate(savedInstanceState);
        splash.setKeepOnScreenCondition(() -> !firstFrameReady && SystemClock.uptimeMillis() < deadline);
    }
}
