package com.multicultural.demo;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.util.Log;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

/**
 * FCM 수신 서비스 — 앱이 백그라운드/종료 상태에서도 새 가정통신문 알림을 시스템 트레이에 표시.
 *
 * 백엔드(/notice/send 또는 /notice/upload)가 학부모 토큰으로 FCM 메시지를 보내면
 * Google FCM 인프라가 이 서비스를 깨워 onMessageReceived() 호출 → NotificationManager로 알림.
 *
 * 토큰 갱신은 onNewToken() — 앱 재설치/스토리지 정리 후 토큰 바뀌면 자동 호출.
 * 백엔드 등록은 MainActivity.registerFcmToken()에서 처리 (역할·user_id가 그쪽에 있음).
 */
public class SchoolBridgeMessagingService extends FirebaseMessagingService {
    private static final String TAG = "FCM";
    public  static final String CHANNEL_ID = "schoolbridge_inbox";
    private static final String CHANNEL_NAME = "가정통신문 알림";
    private static final String CHANNEL_DESC = "새 가정통신문이 도착하면 알림을 받습니다";
    private static final int NOTIFICATION_ID_BASE = 1000;
    private static int notificationCounter = 0;

    @Override
    public void onMessageReceived(RemoteMessage remoteMessage) {
        super.onMessageReceived(remoteMessage);

        String title = "새 가정통신문";
        String body  = "통신문이 도착했습니다.";

        // 백엔드는 notification 필드로 보냄 (서버측 default 텍스트, 다국어 매핑 끝난 상태)
        if (remoteMessage.getNotification() != null) {
            String t = remoteMessage.getNotification().getTitle();
            String b = remoteMessage.getNotification().getBody();
            if (t != null && !t.isEmpty()) title = t;
            if (b != null && !b.isEmpty()) body  = b;
        }

        // data 페이로드 — notice_id 등 (앱 열었을 때 해당 통신문으로 점프 가능, 추후)
        String noticeId = remoteMessage.getData().get("notice_id");
        Log.i(TAG, "onMessageReceived title=" + title + " body=" + body + " notice_id=" + noticeId);

        showNotification(title, body, noticeId);
    }

    @Override
    public void onNewToken(String token) {
        super.onNewToken(token);
        Log.i(TAG, "onNewToken (재등록 필요): …" + token.substring(Math.max(0, token.length() - 10)));
        // 앱이 켜져 있고 로그인 상태라면 즉시 백엔드에 재등록.
        // 백엔드 등록 호출은 MainActivity 가짐 (currentUserId 보유).
        // 여기선 SharedPreferences에 마지막 토큰 캐시만 — MainActivity가 다음 진입 시 비교 후 등록.
        SharedPreferences prefs = getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE);
        prefs.edit().putString(MainActivity.PREF_FCM_TOKEN, token).apply();
        // 즉시 등록 시도 — 이미 로그인되어 있으면 백엔드에 push
        MainActivity.tryRegisterFcmTokenFromService(this, token);
    }

    private void showNotification(String title, String body, String noticeId) {
        ensureChannel();

        // 알림 탭 → MainActivity 열기 (이미 떠있으면 재사용)
        Intent intent = new Intent(this, MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (noticeId != null) intent.putExtra("fcm_notice_id", noticeId);
        int piFlags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        PendingIntent pendingIntent = PendingIntent.getActivity(this, 0, intent, piFlags);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_email)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_MESSAGE)
                .setAutoCancel(true)
                .setContentIntent(pendingIntent);

        NotificationManagerCompat manager = NotificationManagerCompat.from(this);
        try {
            manager.notify(NOTIFICATION_ID_BASE + (notificationCounter++ % 100), builder.build());
        } catch (SecurityException error) {
            // POST_NOTIFICATIONS 권한 없음 (Android 13+) — 사용자가 거부했을 때
            Log.w(TAG, "notify SecurityException (권한 없음): " + error.getMessage());
        }
    }

    private void ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription(CHANNEL_DESC);
            channel.enableVibration(true);
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(channel);
        }
    }
}
