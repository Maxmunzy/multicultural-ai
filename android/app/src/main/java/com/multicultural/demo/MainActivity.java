package com.multicultural.demo;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.pdf.PdfRenderer;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.TextUtils;
import android.text.style.BackgroundColorSpan;
import android.text.style.ForegroundColorSpan;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import com.google.firebase.messaging.FirebaseMessaging;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Calendar;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {
    // BuildConfig.BASE_URL 로 분리 — 서버 IP 는 빌드 시점에 주입.
    // 빌드: ./gradlew assembleDebug -Pschoolbridge.baseUrl=http://YOUR_SERVER:8000
    // 자세한 가이드는 android/README.md 참고.
    private static final String BASE_URL = BuildConfig.BASE_URL;
    private static final String DEFAULT_PARENT_ID = "parent_001";
    private static final String DEFAULT_TEACHER_ID = "teacher_001";
    // FCM/Persistent login용 — Service 클래스에서도 참조하기 때문에 public.
    public  static final String PREFS_NAME = "app";
    public  static final String PREF_KEY_LANG = "selected_lang";
    public  static final String PREF_USER_ID  = "user_id";   // 자동 로그인용
    public  static final String PREF_ROLE     = "role";       // "teacher" | "parent"
    public  static final String PREF_FCM_TOKEN = "fcm_token"; // 마지막 등록한 토큰 (재등록 비교용)
    // 인박스 NEW 뱃지용 — user_id 별로 본 적 있는 notice_id Set + 첫 로드 마킹 플래그
    private static final String PREF_SEEN_PREFIX = "seen_notices_";  // + user_id
    private static final String PREF_INBOX_INIT_PREFIX = "inbox_init_";  // + user_id
    // Android 13+ 알림 권한 런타임 요청 코드
    private static final int    REQUEST_POST_NOTIFICATIONS = 2001;

    // SAF 파일 픽커 요청 코드 (legacy startActivityForResult 사용 — minSdk 23 호환).
    private static final int REQUEST_PICK_FILE        = 1001;
    // OcrActivity 요청 코드
    private static final int REQUEST_OCR              = 1002;
    // 학부모 PDF 업로드 요청 코드
    private static final int REQUEST_PICK_FILE_PARENT = 1003;

    // ── Daon design tokens ──
    private static final int COLOR_PEACH        = Color.parseColor("#DBEAFE"); // light blue
    private static final int COLOR_PEACH_DEEP   = Color.parseColor("#3B67FF"); // primary blue
    private static final int COLOR_PEACH_INK    = Color.parseColor("#1A237E"); // dark navy
    private static final int COLOR_MINT         = Color.parseColor("#DCFCE7"); // light green
    private static final int COLOR_MINT_DEEP    = Color.parseColor("#22C55E"); // success green
    private static final int COLOR_MINT_INK     = Color.parseColor("#15803D"); // dark green
    private static final int COLOR_LEMON        = Color.parseColor("#FEF9C3"); // light yellow
    private static final int COLOR_LEMON_INK    = Color.parseColor("#854D0E"); // amber
    private static final int COLOR_LAVENDER     = Color.parseColor("#EEF2FF"); // light indigo
    private static final int COLOR_LAVENDER_INK = Color.parseColor("#3B67FF"); // primary blue
    private static final int COLOR_SKY          = Color.parseColor("#DBEAFE"); // light blue
    private static final int COLOR_PAPER        = Color.parseColor("#FFFFFF"); // white
    private static final int COLOR_PAPER2       = Color.parseColor("#EEF2FF"); // very light blue
    private static final int COLOR_INK          = Color.parseColor("#111827"); // near black
    private static final int COLOR_INK2         = Color.parseColor("#374151"); // dark gray
    private static final int COLOR_INK3         = Color.parseColor("#6B7280"); // medium gray
    private static final int COLOR_INK4         = Color.parseColor("#9CA3AF"); // light gray
    private static final int COLOR_LINE         = Color.parseColor("#E5E7EB"); // border gray

    private static final String[] LANG_CODES  = {"vi_demo", "en", "ru", "ms", "mn", "vi", "zh", "th", "ja"};
    private static final String[] LANG_LABELS = {"🇻🇳 Tiếng Việt (시연용)", "🇺🇸 English", "🇷🇺 Русский", "🇲🇾 Bahasa Melayu", "🇲🇳 Монгол", "🇻🇳 Tiếng Việt", "🇨🇳 中文", "🇹🇭 ไทย", "🇯🇵 日本語"};
    private static final String[] LANG_NAMES  = {"베트남어 (시연용)", "영어", "러시아어", "말레이시아어", "몽골어", "베트남어", "중국어", "태국어", "일본어"};
    private static final String[] LANG_FLAGS  = {"VN", "EN", "RU", "MY", "MN", "VN", "CN", "TH", "JP"};
    private static final String[] LANG_NATIVE = {"Tiếng Việt (시연용)", "English", "Русский", "Bahasa", "Монгол", "Tiếng Việt", "中文", "ไทย", "日本語"};

    private static String selectedLanguage = "ko_easy";
    private String currentUserId = "";
    private String pendingRole = "";

    private static final float TEXT_SIZE_MIN = 13f;
    private static final float TEXT_SIZE_MAX = 24f;
    private float currentTextSize = 15f;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final List<NoticeItem> inbox = new ArrayList<>();

    private LinearLayout content;
    private EditText loginIdInput;
    private EditText titleInput;
    private EditText bodyInput;
    private EditText parentIdInput;
    private TextView sendResultText;
    private LinearLayout inboxListBox;
    private TextView inboxEmptyText;
    private TextView analysisStatusText;
    private TextView checklistText;
    private TextView easyKoText;
    private TextView translationText;
    private LinearLayout glossaryChipsBox;
    private LinearLayout linkActionsBox;
    private LinearLayout bottomActionsBar;
    private Button linkSideTabButton;
    private Button calendarActionButton;
    private Button playButton;
    private Button easyKoPlayButton;
    private Button langPillBtn;

    private NoticeItem selectedNotice;
    private MediaPlayer player;
    // OCR로 업로드된 가정통신문의 ML Kit layout JSON. analyze 호출 시 동일 notice_id면
    // payload에 layout_json으로 실어보내 backend highlight_mapper가 카드 ↔ bbox 매칭.
    private final Map<String, String> ocrLayoutByNoticeId = new LinkedHashMap<>();
    private final List<String> currentActionUrls = new ArrayList<>();
    private JSONArray currentCalendarEvents = null;
    private static final Pattern URL_PATTERN = Pattern.compile(
            "https?://[^\\s\\])}>,]+|www\\.[^\\s\\])}>,]+",
            Pattern.CASE_INSENSITIVE);
    // 선생님이 첨부한 파일 (업로드 미리보기 → 발송 버튼 클릭 시 사용)
    private byte[] pendingFileBytes = null;
    private String pendingFilename = null;
    private String pendingPreviewUrl = null;     // /static/notices/preview-xxx.pdf 등
    private String pendingPreviewMime = null;    // application/pdf, image/jpeg 등
    private LinearLayout teacherPreviewBox = null;  // 선생님 화면 PDF 미리보기 영역
    private LinearLayout teacherTitleCard = null;   // 파일 업로드 시 숨길 제목 입력 카드
    private LinearLayout teacherBodyCard = null;    // 파일 업로드 시 숨길 본문 입력 카드
    private String currentTtsUrl = "";
    private String currentEasyKoTtsUrl = "";
    private float ttsSpeed = 1.0f;
    private Button[] speedButtons;

    // STT / 음성 질문
    private JSONArray currentCards = null;
    private JSONArray currentInfoCards = null;
    private String currentAnalyzedNoticeId = "";
    private JSONArray currentAnalysisItems = null;
    private String currentNoticeTitle = "";
    private String currentNoticeTitleTranslated = "";
    // 분석 화면 헤더 — 응답 도착 시 heuristic title / 번역 부제로 갱신
    private TextView noticeTitleView;
    private TextView noticeTitleLangChip;   // "🌐 ENGLISH" 같은 언어 라벨
    private TextView noticeTitleSubView;    // 번역된 제목 본문
    private SpeechRecognizer speechRecognizer;
    private TextToSpeech ttsEngine;
    private Button sttButton;
    private boolean ttsEngineReady = false;

    // lang → { category → [팁 문장, 매칭키워드1, 매칭키워드2, ...] }
    private static final Map<String, Map<String, String[]>> STT_TIPS = new LinkedHashMap<>();
    static {
        // 한국어 (ko_easy, 데모 기본)
        Map<String, String[]> ko = new LinkedHashMap<>();
        ko.put("주제",   new String[]{"이번 주제가 뭐예요?",      "주제", "제목"});
        ko.put("준비물", new String[]{"준비물이 뭐예요?",          "준비물", "뭐 챙"});
        ko.put("일정",   new String[]{"일정이 언제예요?",          "일정", "날짜", "언제"});
        ko.put("비용",   new String[]{"비용이 얼마예요?",          "비용", "얼마", "돈"});
        ko.put("제출",   new String[]{"뭘 제출해야 해요?",         "제출", "내야", "서류"});
        ko.put("건강",   new String[]{"건강 안전 내용 알려주세요",  "건강", "안전"});
        STT_TIPS.put("ko_easy", ko);

        // 베트남어
        Map<String, String[]> vi = new LinkedHashMap<>();
        vi.put("주제",   new String[]{"Chủ đề thông báo là gì?",    "chủ đề", "tiêu đề"});
        vi.put("준비물", new String[]{"Cần mang gì?",                "mang", "đồ dùng", "cần mang"});
        vi.put("일정",   new String[]{"Lịch là khi nào?",            "lịch", "khi nào", "ngày"});
        vi.put("비용",   new String[]{"Chi phí là bao nhiêu?",       "phí", "tiền", "bao nhiêu"});
        vi.put("제출",   new String[]{"Cần nộp gì?",                 "nộp", "cần nộp"});
        vi.put("건강",   new String[]{"Thông tin sức khỏe?",         "sức khỏe", "an toàn"});
        STT_TIPS.put("vi", vi);
        STT_TIPS.put("vi_demo", ko); // 시연용: 한국인 발표자가 한국어로 말함

        // 영어
        Map<String, String[]> en = new LinkedHashMap<>();
        en.put("주제",   new String[]{"What is this notice about?",   "about", "topic", "subject"});
        en.put("준비물", new String[]{"What do I need to bring?",     "bring", "supplies", "need to bring"});
        en.put("일정",   new String[]{"When is the schedule?",        "when", "schedule", "date"});
        en.put("비용",   new String[]{"How much does it cost?",       "cost", "how much", "fee"});
        en.put("제출",   new String[]{"What do I need to submit?",    "submit", "hand in"});
        en.put("건강",   new String[]{"Any health or safety info?",   "health", "safety"});
        STT_TIPS.put("en", en);

        // 러시아어
        Map<String, String[]> ru = new LinkedHashMap<>();
        ru.put("주제",   new String[]{"О чём это уведомление?",      "о чём", "тема"});
        ru.put("준비물", new String[]{"Что нужно принести?",         "принести", "взять"});
        ru.put("일정",   new String[]{"Когда по расписанию?",        "когда", "расписание", "дата"});
        ru.put("비용",   new String[]{"Сколько стоит?",              "сколько", "стоит", "деньги"});
        ru.put("제출",   new String[]{"Что нужно сдать?",            "сдать", "нужно сдать"});
        ru.put("건강",   new String[]{"Информация о здоровье?",      "здоровье", "безопасность"});
        STT_TIPS.put("ru", ru);

        // 말레이어
        Map<String, String[]> ms = new LinkedHashMap<>();
        ms.put("주제",   new String[]{"Apakah topik notis ini?",     "topik", "tajuk"});
        ms.put("준비물", new String[]{"Apa yang perlu dibawa?",      "bawa", "perlu dibawa"});
        ms.put("일정",   new String[]{"Bila jadualnya?",             "bila", "jadual", "tarikh"});
        ms.put("비용",   new String[]{"Berapakah kosnya?",           "kos", "berapa", "wang"});
        ms.put("제출",   new String[]{"Apa yang perlu diserahkan?",  "serahkan", "hantar"});
        ms.put("건강",   new String[]{"Maklumat kesihatan?",         "kesihatan", "keselamatan"});
        STT_TIPS.put("ms", ms);

        // 몽골어
        Map<String, String[]> mn = new LinkedHashMap<>();
        mn.put("주제",   new String[]{"Энэ мэдэгдэл юуны тухай вэ?", "юуны тухай", "гарчиг"});
        mn.put("준비물", new String[]{"Юу авчрах хэрэгтэй вэ?",      "авчрах", "юу авч"});
        mn.put("일정",   new String[]{"Хуваарь хэзээ вэ?",           "хуваарь", "хэзээ", "огноо"});
        mn.put("비용",   new String[]{"Хэдэн төгрөг вэ?",            "төгрөг", "хэдэн", "мөнгө"});
        mn.put("제출",   new String[]{"Юу өгөх хэрэгтэй вэ?",       "өгөх", "юу өг"});
        mn.put("건강",   new String[]{"Эрүүл мэндийн мэдээлэл?",    "эрүүл мэнд", "аюулгүй"});
        STT_TIPS.put("mn", mn);

        // 중국어
        Map<String, String[]> zh = new LinkedHashMap<>();
        zh.put("주제",   new String[]{"这次通知的主题是什么？",  "主题", "内容"});
        zh.put("준비물", new String[]{"需要带什么？",            "带什么", "准备"});
        zh.put("일정",   new String[]{"日程是什么时候？",        "日程", "什么时候", "日期"});
        zh.put("비용",   new String[]{"费用是多少？",            "费用", "多少钱", "钱"});
        zh.put("제출",   new String[]{"需要提交什么？",          "提交", "交什么"});
        zh.put("건강",   new String[]{"有健康安全信息吗？",      "健康", "安全"});
        STT_TIPS.put("zh", zh);

        // 태국어
        Map<String, String[]> th = new LinkedHashMap<>();
        th.put("주제",   new String[]{"หัวข้อของประกาศนี้คืออะไร?", "หัวข้อ", "เรื่อง"});
        th.put("준비물", new String[]{"ต้องนำอะไรมาบ้าง?",          "นำอะไร", "เตรียม"});
        th.put("일정",   new String[]{"ตารางเวลาเมื่อไหร่?",        "ตาราง", "เมื่อไหร่", "วัน"});
        th.put("비용",   new String[]{"ค่าใช้จ่ายเท่าไหร่?",       "ค่าใช้จ่าย", "เท่าไหร่", "เงิน"});
        th.put("제출",   new String[]{"ต้องส่งอะไรบ้าง?",          "ส่งอะไร", "ยื่น"});
        th.put("건강",   new String[]{"ข้อมูลสุขภาพมีอะไรบ้าง?",  "สุขภาพ", "ความปลอดภัย"});
        STT_TIPS.put("th", th);

        // 일본어
        Map<String, String[]> ja = new LinkedHashMap<>();
        ja.put("주제",   new String[]{"このお知らせのテーマは何ですか？", "テーマ", "内容"});
        ja.put("준비물", new String[]{"何を持ってきますか？",            "持ってきます", "準備"});
        ja.put("일정",   new String[]{"スケジュールはいつですか？",      "スケジュール", "いつ", "日程"});
        ja.put("비용",   new String[]{"費用はいくらですか？",            "費用", "いくら", "お金"});
        ja.put("제출",   new String[]{"何を提出しますか？",              "提出", "出します"});
        ja.put("건강",   new String[]{"健康・安全情報を教えてください",  "健康", "安全"});
        STT_TIPS.put("ja", ja);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        selectedLanguage = getSavedLanguage();
        ttsEngine = new TextToSpeech(this, status -> {
            ttsEngineReady = (status == TextToSpeech.SUCCESS);
        });
        // Persistent login — 저장된 역할/ID 있으면 로그인 화면 건너뛰고 바로 홈으로.
        // 없으면 종전대로 역할 선택 화면.
        if (!tryAutoLogin()) {
            showLoginScreen();
        }
    }

    @Override
    protected void onDestroy() {
        releasePlayer();
        if (speechRecognizer != null) { speechRecognizer.destroy(); speechRecognizer = null; }
        if (ttsEngine != null) { ttsEngine.stop(); ttsEngine.shutdown(); ttsEngine = null; }
        executor.shutdownNow();
        super.onDestroy();
    }

    private void clearScreenRefs() {
        loginIdInput = null;
        titleInput = null;
        bodyInput = null;
        teacherTitleCard = null;
        teacherBodyCard = null;
        teacherPreviewBox = null;
        parentIdInput = null;
        sendResultText = null;
        inboxListBox = null;
        inboxEmptyText = null;
        analysisStatusText = null;
        checklistText = null;
        easyKoText = null;
        translationText = null;
        glossaryChipsBox = null;
        playButton = null;
        easyKoPlayButton = null;
        langPillBtn = null;
    }

    // ============================================================
    //  SCREEN 1 · LOGIN  (역할 선택 → ID 입력 → 들어가기)
    // ============================================================
    private void showLoginScreen() {
        clearScreenRefs();
        currentUserId = "";
        buildScreen(null, "가정통신문 AI", "AI 번역 · 9개 언어 지원", false, -1, false);

        content.addView(heroLoginCard());
        content.addView(languageSelectCard());

        if (pendingRole.isEmpty()) {
            content.addView(sectionLabel("역할 선택"));
            content.addView(roleChoiceCard("👩‍🏫", "선생님으로 시작",
                    "가정통신문을 작성하고 발송", COLOR_PEACH, COLOR_PEACH_INK,
                    v -> { pendingRole = "teacher"; showLoginScreen(); }));
            content.addView(roleChoiceCard("👨‍👩‍👧", "학부모로 시작",
                    "받은 통신문을 모국어로 확인", COLOR_MINT, COLOR_MINT_INK,
                    v -> { pendingRole = "parent"; showLoginScreen(); }));
        } else {
            boolean isTeacher = pendingRole.equals("teacher");
            content.addView(sectionLabel(isTeacher ? "선생님 ID 입력" : "학부모 ID 입력"));
            loginIdInput = input(isTeacher ? "teacher_001" : "parent_001",
                                  isTeacher ? DEFAULT_TEACHER_ID : DEFAULT_PARENT_ID);
            content.addView(loginIdInput);

            TextView hint = text(isTeacher
                    ? "데모 계정: teacher_001 · teacher_002"
                    : "데모 계정: parent_001 · parent_002 · parent_003",
                    11, COLOR_INK3, false);
            hint.setPadding(dp(4), 0, 0, dp(8));
            content.addView(hint);

            content.addView(bigPrimaryButton(isTeacher ? "선생님으로 들어가기 →" : "학부모로 들어가기 →", v -> {
                String id = safe(loginIdInput.getText().toString());
                if (id.isEmpty()) id = isTeacher ? DEFAULT_TEACHER_ID : DEFAULT_PARENT_ID;
                currentUserId = id;
                String role = pendingRole;
                pendingRole = "";
                // 자동 로그인 + FCM 알림용으로 prefs 저장.
                saveLoginPrefs(role, id);
                // Android 13+ 알림 권한 (없으면 토큰 받아도 시스템 트레이에 안 뜸)
                ensureNotificationPermission();
                // FCM 토큰 받아서 백엔드 등록 — push가 이 user_id로 도달하게.
                fetchAndRegisterFcmToken();
                if (role.equals("teacher")) showTeacherHome();
                else {
                    showParentHome();
                }
            }));
            content.addView(outlineButton("← 역할 다시 선택", v -> {
                pendingRole = "";
                showLoginScreen();
            }));
        }
    }

    private LinearLayout heroLoginCard() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(22), dp(26), dp(22), dp(22));
        box.setLayoutParams(spacedParams());
        GradientDrawable bg = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                new int[]{COLOR_PEACH, blend(COLOR_PEACH, COLOR_PEACH_DEEP, 0.35f)});
        bg.setCornerRadius(dp(22));
        box.setBackground(bg);
        box.setElevation(dp(2));

        TextView chip = text("📌  탑재형 AI 모듈", 11, COLOR_PEACH_INK, true);
        chip.setBackground(roundedFill(Color.argb(180, 255, 255, 255), dp(999)));
        chip.setPadding(dp(10), dp(5), dp(10), dp(5));
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        chip.setLayoutParams(cp);
        box.addView(chip);

        TextView emoji = new TextView(this);
        emoji.setText("📬");
        emoji.setTextSize(36);
        emoji.setPadding(0, dp(10), 0, 0);
        box.addView(emoji);

        TextView title = text("환영합니다", 24, COLOR_PEACH_INK, true);
        title.setLetterSpacing(-0.02f);
        title.setPadding(0, dp(6), 0, 0);
        box.addView(title);

        TextView body = text("학교 알림장 앱에 들어가는 AI 번역 모듈입니다.\n선생님 ↔ 학부모 모국어 소통을 도와드려요.",
                13, COLOR_PEACH_INK, false);
        body.setLineSpacing(0, 1.5f);
        body.setPadding(0, dp(8), 0, 0);
        box.addView(body);
        return box;
    }

    private LinearLayout roleChoiceCard(String emoji, String title, String desc,
                                        int bgColor, int inkColor, View.OnClickListener listener) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.HORIZONTAL);
        box.setGravity(Gravity.CENTER_VERTICAL);
        box.setPadding(dp(18), dp(18), dp(20), dp(18));
        box.setLayoutParams(spacedParams());
        GradientDrawable bg = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR, cardGradient(bgColor));
        bg.setCornerRadius(dp(18));
        box.setBackground(bg);
        box.setElevation(dp(1));
        box.setClickable(true);
        box.setFocusable(true);
        box.setOnClickListener(listener);

        TextView ic = new TextView(this);
        ic.setText(emoji);
        ic.setTextSize(30);
        LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        ip.setMargins(0, 0, dp(14), 0);
        ic.setLayoutParams(ip);
        box.addView(ic);

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setLayoutParams(new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        TextView t = text(title, 16, inkColor, true);
        t.setLetterSpacing(-0.01f);
        col.addView(t);
        TextView d = text(desc, 12, inkColor, false);
        d.setAlpha(0.85f);
        d.setPadding(0, dp(2), 0, 0);
        col.addView(d);
        box.addView(col);

        TextView arrow = text("→", 20, inkColor, true);
        box.addView(arrow);
        return box;
    }

    private LinearLayout languageSelectCard() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.HORIZONTAL);
        box.setGravity(Gravity.CENTER_VERTICAL);
        box.setPadding(dp(18), dp(16), dp(18), dp(16));
        box.setLayoutParams(spacedParams());
        GradientDrawable bg = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR, cardGradient(COLOR_SKY));
        bg.setCornerRadius(dp(18));
        box.setBackground(bg);
        box.setElevation(dp(1));
        box.setClickable(true);
        box.setFocusable(true);
        box.setOnClickListener(v -> showLanguageDialog());

        TextView ic = new TextView(this);
        ic.setText("🌐");
        ic.setTextSize(28);
        LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        ip.setMargins(0, 0, dp(14), 0);
        ic.setLayoutParams(ip);
        box.addView(ic);

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setLayoutParams(new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        TextView t = text("Language", 16, COLOR_INK, true);
        col.addView(t);
        TextView d = text(selectedLanguageNative() + " · Tap to change", 12, COLOR_INK2, false);
        d.setPadding(0, dp(2), 0, 0);
        col.addView(d);
        box.addView(col);

        TextView arrow = text("→", 20, COLOR_INK, true);
        box.addView(arrow);
        return box;
    }

    // ============================================================
    //  SCREEN 2 · TEACHER HOME  (가통문 작성/발송)
    // ============================================================
    private void showTeacherHome() {
        clearScreenRefs();
        buildScreen("안녕하세요,", currentUserId + "님 ✏️",
                    "통신문 작성", true, 1, false);


        // 받는 학부모
        content.addView(formCard("받는 학부모", () -> {
            parentIdInput = input("parent_001", DEFAULT_PARENT_ID);
            return parentIdInput;
        }));

        // 제목 (파일 업로드 시 숨김)
        teacherTitleCard = formCard("제목", () -> {
            titleInput = input("예: 현장학습 안내", "현장학습 안내");
            titleInput.setBackground(transparentBg());
            titleInput.setPadding(0, dp(2), 0, dp(2));
            titleInput.setTextSize(17);
            titleInput.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
            return titleInput;
        });
        content.addView(teacherTitleCard);

        // 내용 (파일 업로드 시 숨김)
        teacherBodyCard = formCard("내용 (한국어)", () -> {
            bodyInput = multiInput("가정통신문 본문", sampleNotice());
            bodyInput.setBackground(transparentBg());
            bodyInput.setPadding(0, dp(2), 0, dp(2));
            bodyInput.setTextSize(14);
            return bodyInput;
        });
        content.addView(teacherBodyCard);

        // AI 헬프 카드 (정보용 — 클릭 안 됨)
        content.addView(aiHelperCard());

        // 파일 업로드 시 PDF/이미지 미리보기 카드가 들어가는 영역
        teacherPreviewBox = new LinearLayout(this);
        teacherPreviewBox.setOrientation(LinearLayout.VERTICAL);
        teacherPreviewBox.setLayoutParams(spacedParams());
        teacherPreviewBox.setVisibility(View.GONE);
        content.addView(teacherPreviewBox);

        // 발송 결과
        sendResultText = text("", 13, COLOR_INK3, false);
        sendResultText.setVisibility(View.GONE);
        sendResultText.setLineSpacing(0, 1.45f);
        sendResultText.setPadding(dp(4), dp(4), dp(4), 0);
        content.addView(sendResultText);

        // 발송 CTA (full width primary)
        content.addView(bigPrimaryButton("📤  통신문 발송", v -> sendNotice()));
        // 파일 업로드 (HWP/PDF/TXT) — 선택 시 SAF 픽커 → 백엔드 /notice/upload
        content.addView(outlineButton("📎  PDF/HWP 파일 업로드", v -> launchFilePicker()));
        content.addView(smallTextButton("← 로그아웃", v -> logout()));
    }

    private LinearLayout templateChip(String label, boolean active, View.OnClickListener listener) {
        TextView chip = new TextView(this);
        chip.setText(label);
        chip.setTextSize(13);
        chip.setTextColor(active ? COLOR_PEACH_INK : COLOR_INK2);
        chip.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        chip.setPadding(dp(14), dp(9), dp(14), dp(9));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(active ? COLOR_PEACH : Color.WHITE);
        bg.setCornerRadius(dp(999));
        if (!active) bg.setStroke(dp(1), COLOR_LINE);
        chip.setBackground(bg);
        chip.setClickable(true);
        if (listener != null) {
            chip.setOnClickListener(listener);
        } else {
            chip.setOnClickListener(v -> notImplementedToast(label));
        }
        LinearLayout wrap = new LinearLayout(this);
        wrap.addView(chip);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        p.setMargins(0, 0, dp(6), 0);
        wrap.setLayoutParams(p);
        return wrap;
    }

    private void notImplementedToast(String featureName) {
        String label = featureName == null ? "" : featureName.trim();
        String msg = label.isEmpty()
                ? "기능 미구현 — 데모 베타"
                : label + " — 기능 미구현 (데모 베타)";
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    }

    private LinearLayout formCard(String label, java.util.concurrent.Callable<View> bodyFactory) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(14), dp(12), dp(14), dp(12));
        box.setLayoutParams(spacedParams());
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(16));
        bg.setStroke(dp(1), COLOR_LINE);
        box.setBackground(bg);
        box.setElevation(dp(0.5f));

        TextView lab = text(label, 11, COLOR_INK3, true);
        lab.setAllCaps(true);
        lab.setLetterSpacing(0.06f);
        lab.setPadding(0, 0, 0, dp(6));
        box.addView(lab);

        try {
            View v = bodyFactory.call();
            if (v != null) box.addView(v);
        } catch (Exception ignored) {}
        return box;
    }

    private LinearLayout aiHelperCard() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.HORIZONTAL);
        box.setGravity(Gravity.CENTER_VERTICAL);
        box.setPadding(dp(14), dp(12), dp(14), dp(12));
        box.setLayoutParams(spacedParams());
        GradientDrawable bg = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR, cardGradient(COLOR_LEMON));
        bg.setCornerRadius(dp(16));
        box.setBackground(bg);

        TextView ic = new TextView(this);
        ic.setText("✨");
        ic.setTextSize(20);
        LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        ip.setMargins(0, 0, dp(10), 0);
        ic.setLayoutParams(ip);
        box.addView(ic);

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setLayoutParams(new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        TextView t = text("학부모가 모국어로 받아봅니다", 14, COLOR_LEMON_INK, true);
        col.addView(t);
        TextView d = text("학부모 화면 우측 상단 ✨ 버튼으로 9개 언어 번역", 11, COLOR_LEMON_INK, false);
        d.setAlpha(0.85f);
        d.setPadding(0, dp(2), 0, 0);
        col.addView(d);
        box.addView(col);
        return box;
    }

    // ============================================================
    //  SCREEN 3 · PARENT HOME  (받은 통신문 목록)
    // ============================================================
    private void showParentHome() {
        clearScreenRefs();
        buildScreen(greetingForLanguage(), currentUserId + "님 👋",
                    uiText("received_notices"), true, 0, true);

        content.addView(languageSelectCard());

        inboxListBox = new LinearLayout(this);
        inboxListBox.setOrientation(LinearLayout.VERTICAL);
        inboxListBox.setLayoutParams(spacedParams());
        content.addView(sectionLabel(uiText("new_notice")));
        content.addView(inboxListBox);

        inboxEmptyText = text(uiText("loading_inbox"), 13, COLOR_INK3, false);
        inboxEmptyText.setPadding(dp(4), dp(8), dp(4), 0);
        inboxListBox.addView(inboxEmptyText);

        content.addView(outlineButton("🔄  " + uiText("refresh_inbox"), v -> loadInbox()));
        content.addView(outlineButton("📥  통신문 직접 올리기", v -> showUploadDialog()));
        content.addView(smallTextButton("← " + uiText("logout"), v -> logout()));

        loadInbox();
    }

    private void loadInbox() {
        inbox.clear();
        if (inboxEmptyText != null) {
            inboxEmptyText.setVisibility(View.VISIBLE);
            inboxEmptyText.setText(uiText("loading_inbox"));
        }
        if (inboxListBox != null) {
            int childCount = inboxListBox.getChildCount();
            for (int i = childCount - 1; i >= 0; i--) {
                if (inboxListBox.getChildAt(i) != inboxEmptyText) inboxListBox.removeViewAt(i);
            }
        }
        getJson("/notice/inbox/" + currentUserId, result -> {
            if (!result.error.isEmpty()) {
                if (inboxEmptyText != null) inboxEmptyText.setText(uiText("server_error") + "\n" + result.error);
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                JSONArray data = json.optJSONArray("data");
                if (data == null || data.length() == 0) {
                    if (inboxEmptyText != null) inboxEmptyText.setText(uiText("empty_inbox"));
                    return;
                }
                for (int i = 0; i < data.length(); i++) {
                    JSONObject item = data.getJSONObject(i);
                    String origUrl = item.optString("original_file_url", null);
                    if (origUrl != null && origUrl.isEmpty()) origUrl = null;
                    String origName = item.optString("original_filename", null);
                    if (origName != null && origName.isEmpty()) origName = null;
                    String mime = item.optString("mime_type", null);
                    if (mime != null && mime.isEmpty()) mime = null;
                    inbox.add(new NoticeItem(
                            safeString(item, "notice_id"),
                            safeString(item, "teacher_id"),
                            safeString(item, "text"),
                            origUrl, origName, mime
                    ));
                }
                renderInboxList();
            } catch (Exception error) {
                if (inboxEmptyText != null) inboxEmptyText.setText("응답 파싱 실패\n" + result.body);
            }
        });
    }

    private void renderInboxList() {
        if (inboxListBox == null) return;
        if (inboxEmptyText != null) inboxEmptyText.setVisibility(View.GONE);
        // remove any leftover items
        for (int i = inboxListBox.getChildCount() - 1; i >= 0; i--) {
            if (inboxListBox.getChildAt(i) != inboxEmptyText) inboxListBox.removeViewAt(i);
        }
        // NEW 뱃지 — 처음 로드면 모두 seen 처리(과거 통신문 NEW 안 표시), 이후엔 seen 안 된 것만 NEW
        boolean firstTime = !isInboxInitialized();
        Set<String> seen = firstTime ? new HashSet<>() : getSeenNoticeIds();
        String[] avatarEmojis = {"🍱", "📅", "📢", "🏃", "📝", "📖"};
        int[] avatarColors  = {COLOR_MINT, COLOR_LAVENDER, COLOR_PEACH, COLOR_LEMON, COLOR_SKY, COLOR_PAPER2};
        int[] avatarInks    = {COLOR_MINT_INK, COLOR_LAVENDER_INK, COLOR_PEACH_INK, COLOR_LEMON_INK, Color.parseColor("#1F5B8A"), COLOR_INK3};
        for (int i = 0; i < inbox.size(); i++) {
            NoticeItem n = inbox.get(i);
            String emoji = avatarEmojis[i % avatarEmojis.length];
            int avatarBg = avatarColors[i % avatarColors.length];
            int avatarInk = avatarInks[i % avatarInks.length];
            boolean isNew = !firstTime && !seen.contains(n.noticeId);
            inboxListBox.addView(noticeListCard(n, emoji, avatarBg, avatarInk, isNew));
        }
        if (firstTime) markAllInboxSeen();
    }

    private View noticeListCard(NoticeItem n, String emoji, int avatarBg, int avatarInk, boolean isNew) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.HORIZONTAL);
        box.setGravity(Gravity.CENTER_VERTICAL);
        box.setPadding(dp(14), dp(13), dp(14), dp(13));
        // wrap 시 LayoutParams 충돌 방지 — 마지막에 frame 또는 box 중 하나에 spacedParams 부여
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(16));
        bg.setStroke(dp(1), COLOR_LINE);
        box.setBackground(bg);
        box.setElevation(dp(0.5f));
        box.setClickable(true);
        box.setFocusable(true);
        box.setOnClickListener(v -> {
            // 탭 시 즉시 seen 마킹 — 다음 렌더링부터 NEW 뱃지 사라짐
            markNoticeSeen(n.noticeId);
            showNoticeDetail(n);
        });
        // 길게 누르기 → 삭제 확인 다이얼로그
        box.setOnLongClickListener(v -> {
            confirmAndDeleteNotice(n);
            return true;
        });

        // avatar
        TextView avatar = new TextView(this);
        avatar.setText(emoji);
        avatar.setTextSize(18);
        avatar.setGravity(Gravity.CENTER);
        avatar.setTextColor(avatarInk);
        GradientDrawable ab = new GradientDrawable();
        ab.setShape(GradientDrawable.OVAL);
        ab.setColor(avatarBg);
        avatar.setBackground(ab);
        int s = dp(38);
        LinearLayout.LayoutParams ap = new LinearLayout.LayoutParams(s, s);
        ap.setMargins(0, 0, dp(12), 0);
        avatar.setLayoutParams(ap);
        box.addView(avatar);

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setLayoutParams(new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        String[] lines = n.text.split("\\r?\\n");
        String title = lines.length > 0 ? lines[0] : n.text;
        TextView t = text(shorten(title, 28), 14, COLOR_INK, true);
        t.setLetterSpacing(-0.01f);
        col.addView(t);
        TextView meta = text("선생님 · 통신문 #" + shorten(n.noticeId, 6), 11, COLOR_INK3, false);
        meta.setPadding(0, dp(2), 0, 0);
        col.addView(meta);
        box.addView(col);

        // unread dot — NEW일 때만 (이전엔 모든 카드에 켜져있어서 NEW 의미가 약했음)
        if (isNew) {
            View dot = new View(this);
            GradientDrawable db = new GradientDrawable();
            db.setShape(GradientDrawable.OVAL);
            db.setColor(COLOR_PEACH_DEEP);
            dot.setBackground(db);
            LinearLayout.LayoutParams dp_ = new LinearLayout.LayoutParams(dp(8), dp(8));
            dot.setLayoutParams(dp_);
            box.addView(dot);
        }

        if (!isNew) {
            box.setLayoutParams(spacedParams());
            return box;
        }
        // NEW 뱃지 — 좌상단 빨간 칩으로 명확히 표시 (FrameLayout 으로 감싸 absolute 위치)
        FrameLayout frame = new FrameLayout(this);
        frame.setLayoutParams(spacedParams());
        FrameLayout.LayoutParams boxFp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT);
        box.setLayoutParams(boxFp);
        frame.addView(box);

        TextView newBadge = new TextView(this);
        newBadge.setText("NEW");
        newBadge.setTextSize(9);
        newBadge.setTextColor(Color.WHITE);
        newBadge.setTypeface(null, Typeface.BOLD);
        newBadge.setLetterSpacing(0.06f);
        newBadge.setPadding(dp(6), dp(2), dp(6), dp(2));
        GradientDrawable badgeBg = new GradientDrawable();
        badgeBg.setColor(Color.parseColor("#E55A45"));
        badgeBg.setCornerRadius(dp(8));
        newBadge.setBackground(badgeBg);
        newBadge.setElevation(dp(2));
        FrameLayout.LayoutParams badgeFp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT);
        badgeFp.gravity = Gravity.TOP | Gravity.START;
        badgeFp.setMargins(dp(8), dp(6), 0, 0);
        newBadge.setLayoutParams(badgeFp);
        frame.addView(newBadge);
        return frame;
    }

    // 카드 길게 누르기 → 삭제 확인 → DELETE /notice/{notice_id} → 수신함 새로고침
    private void confirmAndDeleteNotice(NoticeItem n) {
        String[] lines = n.text.split("\\r?\\n");
        String preview = shorten(lines.length > 0 ? lines[0] : n.text, 30);
        new AlertDialog.Builder(this)
                .setTitle("가정통신문 삭제")
                .setMessage("\"" + preview + "\"\n\n이 가정통신문을 삭제할까요?")
                .setPositiveButton("삭제", (d, w) -> deleteNoticeAndRefresh(n.noticeId))
                .setNegativeButton("취소", null)
                .show();
    }

    private void deleteNoticeAndRefresh(String noticeId) {
        executor.execute(() -> {
            ApiResult result = httpDelete("/notice/" + noticeId);
            runOnUiThread(() -> {
                if (!result.error.isEmpty()) {
                    Toast.makeText(this, "삭제 실패: " + result.error, Toast.LENGTH_SHORT).show();
                    return;
                }
                Toast.makeText(this, "삭제 완료", Toast.LENGTH_SHORT).show();
                loadInbox();  // 수신함 새로고침
            });
        });
    }

    private ApiResult httpDelete(String path) {
        ApiResult result = new ApiResult();
        HttpURLConnection conn = null;
        try {
            URL url = new URL(BASE_URL + path);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("DELETE");
            conn.setConnectTimeout(30000);
            conn.setReadTimeout(30000);
            conn.setRequestProperty("Accept", "application/json");
            if (!currentUserId.isEmpty()) {
                conn.setRequestProperty("X-User-Id", currentUserId);
            }
            int code = conn.getResponseCode();
            InputStream stream = code >= 200 && code < 300
                    ? conn.getInputStream() : conn.getErrorStream();
            result.body = readStream(stream);
            if (code < 200 || code >= 300) {
                result.error = "HTTP " + code + "\n" + result.body;
            }
        } catch (Exception error) {
            result.error = error.getMessage() == null ? error.toString() : error.getMessage();
        } finally {
            if (conn != null) conn.disconnect();
        }
        return result;
    }

    // ============================================================
    //  SCREEN 4 · NOTICE DETAIL  (한국어 원문 + ✨AI 우상단)
    // ============================================================
    private void showNoticeDetail(NoticeItem notice) {
        clearScreenRefs();
        selectedNotice = notice;

        // 이 화면은 buildScreen이 아닌 커스텀 빌드 (탑 액션바 + body)
        FrameLayout outer = new FrameLayout(this);
        outer.setBackground(daonGradient());

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setLayoutParams(new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(0, 0, 0, dp(28));
        scroll.addView(root);

        // 탑 액션 바: ← back  (spacer)  ✨ AI 번역
        LinearLayout topBar = new LinearLayout(this);
        topBar.setOrientation(LinearLayout.HORIZONTAL);
        topBar.setGravity(Gravity.CENTER_VERTICAL);
        topBar.setPadding(dp(14), dp(38), dp(14), dp(8));

        Button back = iconButton("←", v -> showParentHome());
        topBar.addView(back);

        TextView centerLabel = text("통신문", 13, COLOR_INK2, true);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        lp.setMargins(dp(8), 0, dp(8), 0);
        centerLabel.setLayoutParams(lp);
        centerLabel.setGravity(Gravity.CENTER);
        topBar.addView(centerLabel);

        Button aiBtn = aiPillButton(v -> showAIOverlay(notice));
        topBar.addView(aiBtn);
        root.addView(topBar);

        // 본문 영역
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(18), dp(8), dp(18), 0);
        root.addView(content);

        // caption + title
        TextView caption = text("통신문 #" + shorten(notice.noticeId, 8), 11, COLOR_INK3, true);
        caption.setAllCaps(true);
        caption.setLetterSpacing(0.06f);
        caption.setPadding(dp(2), dp(4), 0, dp(4));
        content.addView(caption);

        String[] lines = notice.text.split("\\r?\\n", 2);
        String title = lines.length > 0 ? lines[0] : notice.text;
        noticeTitleView = text(title, 22, COLOR_INK, true);
        noticeTitleView.setLetterSpacing(-0.02f);
        noticeTitleView.setLineSpacing(0, 1.2f);
        noticeTitleView.setPadding(dp(2), 0, dp(2), dp(4));
        content.addView(noticeTitleView);

        // 번역 부제 — 분석 응답 도착 후 채워짐 (없으면 두 view 모두 GONE)
        // 가시성: "🌐 영어" 라벨 칩 + 본문 16sp 진한 잉크 — 한국어 제목과 명확히 구분
        noticeTitleLangChip = text("", 11, COLOR_INK3, true);
        noticeTitleLangChip.setLetterSpacing(0.06f);
        noticeTitleLangChip.setAllCaps(true);
        noticeTitleLangChip.setPadding(dp(2), dp(2), dp(2), dp(2));
        noticeTitleLangChip.setVisibility(View.GONE);
        content.addView(noticeTitleLangChip);

        noticeTitleSubView = text("", 16, COLOR_INK, false);
        noticeTitleSubView.setLetterSpacing(-0.01f);
        noticeTitleSubView.setLineSpacing(0, 1.3f);
        noticeTitleSubView.setPadding(dp(2), 0, dp(2), dp(6));
        noticeTitleSubView.setVisibility(View.GONE);
        content.addView(noticeTitleSubView);

        TextView sender = text("👩‍🏫 " + notice.teacherId, 12, COLOR_INK3, false);
        sender.setPadding(dp(2), 0, 0, dp(14));
        content.addView(sender);

        // 본문: 원본 파일 있으면 PDF/이미지로 표시, 없으면 텍스트 fallback
        if (notice.hasOriginalFile()) {
            content.addView(buildOriginalFileCard(notice));
        } else {
            TextView body = text(notice.text, 14, COLOR_INK, false);
            body.setLineSpacing(0, 1.65f);
            content.addView(cardWithView("한국어 원문", body, Color.WHITE));
        }

        // AI 안내 카드 (탑재형 모듈 강조)
        LinearLayout aiHint = new LinearLayout(this);
        aiHint.setOrientation(LinearLayout.HORIZONTAL);
        aiHint.setGravity(Gravity.CENTER_VERTICAL);
        aiHint.setPadding(dp(14), dp(12), dp(14), dp(12));
        aiHint.setLayoutParams(spacedParams());
        GradientDrawable hbg = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR, cardGradient(COLOR_LEMON));
        hbg.setCornerRadius(dp(16));
        aiHint.setBackground(hbg);
        TextView hi = new TextView(this);
        hi.setText("✨");
        hi.setTextSize(20);
        LinearLayout.LayoutParams hip = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        hip.setMargins(0, 0, dp(10), 0);
        hi.setLayoutParams(hip);
        aiHint.addView(hi);
        LinearLayout hcol = new LinearLayout(this);
        hcol.setOrientation(LinearLayout.VERTICAL);
        hcol.setLayoutParams(new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        TextView ht = text("우측 상단 ✨ 버튼을 누르면", 13, COLOR_LEMON_INK, true);
        hcol.addView(ht);
        TextView hd = text("AI가 모국어로 번역하고 체크리스트를 만들어드려요", 11, COLOR_LEMON_INK, false);
        hd.setAlpha(0.85f);
        hd.setPadding(0, dp(2), 0, 0);
        hcol.addView(hd);
        aiHint.addView(hcol);
        content.addView(aiHint);

        // 하단 mock 액션 행
        LinearLayout actionRow = new LinearLayout(this);
        actionRow.setOrientation(LinearLayout.HORIZONTAL);
        actionRow.setLayoutParams(spacedParams());
        actionRow.addView(mockChipButton("📅 일정 추가", 1f));
        TextView gap1 = new TextView(this); gap1.setWidth(dp(6));
        actionRow.addView(gap1);
        actionRow.addView(mockChipButton("↩ 회신",     1f));
        content.addView(actionRow);

        outer.addView(scroll);
        setContentView(outer);
    }

    private Button aiPillButton(View.OnClickListener listener) {
        Button b = new Button(this);
        b.setText("✨ " + uiText("ai_translate"));
        b.setTextSize(13);
        b.setTextColor(Color.WHITE);
        b.setAllCaps(false);
        b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        b.setPadding(dp(14), dp(8), dp(14), dp(8));
        GradientDrawable bg = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                new int[]{COLOR_PEACH_DEEP, Color.parseColor("#E07744")});
        bg.setCornerRadius(dp(999));
        b.setBackground(bg);
        b.setStateListAnimator(null);
        b.setElevation(dp(4));
        b.setOnClickListener(listener);
        b.setMinHeight(dp(36));
        b.setMinimumHeight(dp(36));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        b.setLayoutParams(p);
        return b;
    }

    private Button iconButton(String label, View.OnClickListener listener) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(20);
        b.setTextColor(COLOR_INK);
        b.setAllCaps(false);
        b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        b.setPadding(0, 0, 0, 0);
        GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.OVAL);
        bg.setColor(Color.argb(180, 255, 255, 255));
        bg.setStroke(dp(1), COLOR_LINE);
        b.setBackground(bg);
        b.setStateListAnimator(null);
        b.setOnClickListener(listener);
        int s = dp(38);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(s, s);
        b.setLayoutParams(p);
        b.setMinHeight(0); b.setMinimumHeight(0);
        return b;
    }

    private Button mockChipButton(String label, float weight) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(13);
        b.setTextColor(COLOR_INK2);
        b.setAllCaps(false);
        b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        b.setPadding(dp(10), dp(12), dp(10), dp(12));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(14));
        bg.setStroke(dp(1), COLOR_LINE);
        b.setBackground(bg);
        b.setStateListAnimator(null);
        // mock — 누르면 "기능 미구현" 안내
        b.setOnClickListener(v -> notImplementedToast(label));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, weight);
        b.setLayoutParams(p);
        return b;
    }

    // ============================================================
    //  ORIGINAL FILE CARD  (PDF / image / fallback)
    // ============================================================
    private LinearLayout buildOriginalFileCard(NoticeItem notice) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setLayoutParams(spacedParams());
        card.setPadding(dp(14), dp(12), dp(14), dp(14));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(16));
        bg.setStroke(dp(1), COLOR_LINE);
        card.setBackground(bg);

        String headerText = "원본 가정통신문";
        if (notice.originalFilename != null) headerText += " · " + notice.originalFilename;
        TextView header = text(headerText, 11, COLOR_INK3, true);
        header.setAllCaps(true);
        header.setLetterSpacing(0.06f);
        header.setPadding(0, 0, 0, dp(10));
        card.addView(header);

        final ImageView imageView = new ImageView(this);
        LinearLayout.LayoutParams ivLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        imageView.setLayoutParams(ivLp);
        imageView.setAdjustViewBounds(true);
        card.addView(imageView);

        final TextView statusText = text("불러오는 중...", 13, COLOR_INK3, false);
        statusText.setPadding(0, dp(8), 0, 0);
        card.addView(statusText);

        final LinearLayout pageNav = new LinearLayout(this);
        pageNav.setOrientation(LinearLayout.HORIZONTAL);
        pageNav.setGravity(Gravity.CENTER_VERTICAL);
        pageNav.setPadding(0, dp(8), 0, 0);
        pageNav.setVisibility(View.GONE);
        card.addView(pageNav);

        String absUrl = notice.originalFileUrl.startsWith("http")
                ? notice.originalFileUrl
                : BASE_URL + notice.originalFileUrl;

        if (notice.isImage()) {
            downloadAndRenderImage(absUrl, imageView, statusText);
        } else if (notice.isPdf()) {
            downloadAndRenderPdf(notice.noticeId, absUrl, imageView, statusText, pageNav);
        } else {
            statusText.setText("지원 안 되는 파일 형식 — 추출 텍스트 표시");
            TextView body = text(notice.text, 14, COLOR_INK, false);
            body.setLineSpacing(0, 1.65f);
            body.setPadding(0, dp(12), 0, 0);
            card.addView(body);
        }
        return card;
    }

    private void downloadAndRenderImage(String absUrl, ImageView iv, TextView status) {
        executor.execute(() -> {
            Bitmap bmp = null;
            String err = null;
            HttpURLConnection conn = null;
            try {
                URL u = new URL(absUrl);
                conn = (HttpURLConnection) u.openConnection();
                conn.setConnectTimeout(30000);
                conn.setReadTimeout(15000);
                try (InputStream is = conn.getInputStream()) {
                    bmp = BitmapFactory.decodeStream(is);
                }
            } catch (Exception e) {
                err = e.getMessage() == null ? e.toString() : e.getMessage();
            } finally {
                if (conn != null) conn.disconnect();
            }
            final Bitmap fbmp = bmp;
            final String ferr = err;
            runOnUiThread(() -> {
                if (fbmp != null) {
                    iv.setImageBitmap(fbmp);
                    status.setVisibility(View.GONE);
                } else {
                    status.setText("이미지 불러오기 실패: " + ferr);
                }
            });
        });
    }

    private void downloadAndRenderPdf(String noticeId, String absUrl, ImageView iv,
                                       TextView status, LinearLayout pageNav) {
        executor.execute(() -> {
            File pdfFile = null;
            String err = null;
            HttpURLConnection conn = null;
            try {
                URL u = new URL(absUrl);
                conn = (HttpURLConnection) u.openConnection();
                conn.setConnectTimeout(30000);
                conn.setReadTimeout(30000);
                pdfFile = new File(getCacheDir(), "notice_" + noticeId + ".pdf");
                try (InputStream is = conn.getInputStream();
                     FileOutputStream fos = new FileOutputStream(pdfFile)) {
                    byte[] buf = new byte[8192];
                    int n;
                    while ((n = is.read(buf)) > 0) fos.write(buf, 0, n);
                }
            } catch (Exception e) {
                err = e.getMessage() == null ? e.toString() : e.getMessage();
                pdfFile = null;
            } finally {
                if (conn != null) conn.disconnect();
            }
            final File fpdf = pdfFile;
            final String ferr = err;
            runOnUiThread(() -> {
                if (fpdf != null && fpdf.exists()) {
                    renderPdfPage(fpdf, 0, iv, status, pageNav);
                } else {
                    status.setText("PDF 불러오기 실패: " + ferr);
                }
            });
        });
    }

    private void renderPdfPage(File pdfFile, int pageIndex, ImageView iv,
                                TextView status, LinearLayout pageNav) {
        PdfRenderer renderer = null;
        ParcelFileDescriptor pfd = null;
        PdfRenderer.Page page = null;
        try {
            pfd = ParcelFileDescriptor.open(pdfFile, ParcelFileDescriptor.MODE_READ_ONLY);
            renderer = new PdfRenderer(pfd);
            int pageCount = renderer.getPageCount();
            if (pageIndex < 0) pageIndex = 0;
            if (pageIndex >= pageCount) pageIndex = pageCount - 1;
            page = renderer.openPage(pageIndex);
            int screenW = getResources().getDisplayMetrics().widthPixels;
            int targetW = Math.min(Math.max(screenW - dp(64), 600), 1600);
            float scale = (float) targetW / page.getWidth();
            int targetH = Math.round(page.getHeight() * scale);
            Bitmap bmp = Bitmap.createBitmap(targetW, targetH, Bitmap.Config.ARGB_8888);
            bmp.eraseColor(Color.WHITE);
            page.render(bmp, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
            iv.setImageBitmap(bmp);
            status.setVisibility(View.GONE);
            if (pageCount > 1) {
                renderPageNav(pdfFile, pageIndex, pageCount, iv, status, pageNav);
            } else {
                pageNav.setVisibility(View.GONE);
            }
        } catch (Exception e) {
            status.setVisibility(View.VISIBLE);
            status.setText("PDF 렌더 실패: " + (e.getMessage() == null ? e.toString() : e.getMessage()));
        } finally {
            if (page != null) try { page.close(); } catch (Exception ignored) {}
            if (renderer != null) try { renderer.close(); } catch (Exception ignored) {}
            if (pfd != null) try { pfd.close(); } catch (Exception ignored) {}
        }
    }

    private void renderPageNav(File pdfFile, int currentPage, int pageCount, ImageView iv,
                                TextView status, LinearLayout pageNav) {
        pageNav.removeAllViews();
        pageNav.setVisibility(View.VISIBLE);
        Button prev = new Button(this);
        prev.setText("‹ 이전");
        prev.setAllCaps(false);
        prev.setEnabled(currentPage > 0);
        prev.setOnClickListener(v -> renderPdfPage(pdfFile, currentPage - 1, iv, status, pageNav));
        pageNav.addView(prev);

        TextView label = text((currentPage + 1) + " / " + pageCount, 12, COLOR_INK2, true);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        label.setLayoutParams(lp);
        label.setGravity(Gravity.CENTER);
        pageNav.addView(label);

        Button next = new Button(this);
        next.setText("다음 ›");
        next.setAllCaps(false);
        next.setEnabled(currentPage < pageCount - 1);
        next.setOnClickListener(v -> renderPdfPage(pdfFile, currentPage + 1, iv, status, pageNav));
        pageNav.addView(next);
    }

    // ============================================================
    //  SCREEN 5 · AI OVERLAY  (분석 결과)
    // ============================================================
    private void showAIOverlay(NoticeItem notice) {
        clearScreenRefs();
        selectedNotice = notice;

        FrameLayout outer = new FrameLayout(this);
        outer.setBackground(daonGradient());

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setLayoutParams(new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(0, 0, 0, dp(80));  // bottomActionsBar(56dp) + margin(16dp) + 여유
        scroll.addView(root);

        // 탑 액션 바: ✕ 닫기  (spacer)  🌐 lang pill
        LinearLayout topBar = new LinearLayout(this);
        topBar.setOrientation(LinearLayout.HORIZONTAL);
        topBar.setGravity(Gravity.CENTER_VERTICAL);
        topBar.setPadding(dp(14), dp(38), dp(14), dp(8));

        Button close = iconButton("✕", v -> showNoticeDetail(notice));
        topBar.addView(close);

        TextView center = text(uiText("ai_translate"), 13, COLOR_INK2, true);
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        clp.setMargins(dp(8), 0, dp(8), 0);
        center.setLayoutParams(clp);
        center.setGravity(Gravity.CENTER);
        topBar.addView(center);

        langPillBtn = makeLangPillButton();
        topBar.addView(langPillBtn);
        root.addView(topBar);

        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(18), dp(8), dp(18), 0);
        root.addView(content);

        // 헤더 영역
        TextView caption = text("✨ AI 분석 결과", 11, COLOR_PEACH_INK, true);
        caption.setAllCaps(true);
        caption.setLetterSpacing(0.06f);
        caption.setPadding(dp(2), dp(2), 0, dp(2));
        content.addView(caption);

        // 통신문 제목 — 클래스 필드에 할당해야 applyAnalysis()의 setText가 자동 연결됨
        String[] noticeTitleLines = notice.text.split("\\r?\\n", 2);
        String initialTitle = noticeTitleLines.length > 0 ? noticeTitleLines[0].trim() : "";
        noticeTitleView = text(initialTitle, 22, COLOR_INK, true);
        noticeTitleView.setLetterSpacing(-0.02f);
        noticeTitleView.setLineSpacing(0, 1.2f);
        noticeTitleView.setPadding(dp(2), 0, dp(2), dp(4));
        content.addView(noticeTitleView);

        // 번역 부제 칩 + 본문 — applyAnalysis()에서 채워짐
        noticeTitleLangChip = text("", 11, COLOR_INK3, true);
        noticeTitleLangChip.setLetterSpacing(0.06f);
        noticeTitleLangChip.setAllCaps(true);
        noticeTitleLangChip.setPadding(dp(2), dp(2), dp(2), dp(2));
        noticeTitleLangChip.setVisibility(View.GONE);
        content.addView(noticeTitleLangChip);

        noticeTitleSubView = text("", 16, COLOR_INK, false);
        noticeTitleSubView.setLetterSpacing(-0.01f);
        noticeTitleSubView.setLineSpacing(0, 1.3f);
        noticeTitleSubView.setPadding(dp(2), 0, dp(2), dp(6));
        noticeTitleSubView.setVisibility(View.GONE);
        content.addView(noticeTitleSubView);

        TextView sub = text(uiText("ai_subtitle"), 12, COLOR_INK3, false);
        sub.setPadding(dp(2), 0, 0, dp(12));
        content.addView(sub);

        // 글자 크기 조절
        content.addView(textSizeControls());

        // 분석 진행 상태 (먼저 보임 → 결과 도착하면 GONE)
        analysisStatusText = text(uiText("analyzing"), 13, COLOR_INK3, false);
        analysisStatusText.setLineSpacing(0, 1.5f);
        LinearLayout statusCard = new LinearLayout(this);
        statusCard.setOrientation(LinearLayout.VERTICAL);
        statusCard.setPadding(dp(16), dp(16), dp(16), dp(16));
        statusCard.setLayoutParams(spacedParams());
        GradientDrawable scbg = new GradientDrawable();
        scbg.setColor(Color.WHITE);
        scbg.setCornerRadius(dp(16));
        scbg.setStroke(dp(1), COLOR_LINE);
        statusCard.setBackground(scbg);
        statusCard.addView(analysisStatusText);
        content.addView(statusCard);

        // 체크리스트 (peach hero) — 처음에는 빈 상태
        checklistText = text("", (int) currentTextSize, COLOR_PEACH_INK, false);
        checklistText.setLineSpacing(0, 1.6f);
        LinearLayout checklistCard = cardWithView("📋  " + uiText("todo"), checklistText, COLOR_PEACH);
        checklistCard.setVisibility(View.GONE);
        content.addView(checklistCard);

        // 쉬운 한국어
        easyKoText = text("", (int) currentTextSize, COLOR_INK, false);
        easyKoText.setLineSpacing(0, 1.6f);
        LinearLayout easyKoCard = cardWithView("🇰🇷  " + uiText("easy_korean"), easyKoText, Color.WHITE);
        easyKoCard.setVisibility(View.GONE);
        content.addView(easyKoCard);

        // 모국어 번역
        translationText = text("", (int) currentTextSize, COLOR_INK, false);
        translationText.setLineSpacing(0, 1.6f);
        String langHeading = selectedLanguageFlag() + "  " + selectedLanguageNative();
        LinearLayout transCard = cardWithView(langHeading, translationText, Color.WHITE);
        transCard.setVisibility(View.GONE);
        content.addView(transCard);

        linkActionsBox = new LinearLayout(this);
        linkActionsBox.setOrientation(LinearLayout.VERTICAL);
        linkActionsBox.setVisibility(View.GONE);
        LinearLayout linkWrap = cardWithView("🔗  신청 바로가기", linkActionsBox, COLOR_SKY);
        linkWrap.setVisibility(View.GONE);
        linkWrap.setTag("linkActionsWrap");
        content.addView(linkWrap);

        // 학교 용어 chips (lemon)
        glossaryChipsBox = new LinearLayout(this);
        glossaryChipsBox.setOrientation(LinearLayout.VERTICAL);
        glossaryChipsBox.setVisibility(View.GONE);
        LinearLayout glossaryWrap = cardWithView("📖  " + uiText("school_terms"), glossaryChipsBox, COLOR_LEMON);
        glossaryWrap.setVisibility(View.GONE);
        content.addView(glossaryWrap);

        // TTS 듣기 버튼
        playButton = bigPrimaryButton(ttsLabel(),
                v -> playTts());
        playButton.setVisibility(View.GONE);
        content.addView(playButton);

        easyKoPlayButton = bigPrimaryButton(easyKoTtsLabel(),
                v -> playTtsUrl(currentEasyKoTtsUrl, easyKoPlayButton, easyKoTtsLabel(), false));
        easyKoPlayButton.setVisibility(View.GONE);
        content.addView(easyKoPlayButton);

        // 재생 속도 조절
        LinearLayout speedRow = buildSpeedControl();
        speedRow.setVisibility(View.GONE);
        speedRow.setTag("speedRow");
        content.addView(speedRow);

        // 음성 질문 (STT)
        LinearLayout sttSection = buildSttSection();
        sttSection.setTag("sttSection");
        content.addView(sttSection);

        // 체크리스트 진입 — 분석 결과 화면에서 진입 (Step 2: C+D 동시)
        // (a) 이 통신문만: BottomSheet 모달로 즉시 체크 (NoticeChecklistDialog)
        // (b) 통합 화면: 이번 주 할 일 (ChecklistActivity, 모든 통신문)
        Button thisChecklistBtn = bigPrimaryButton("📋  이 통신문 체크리스트", v -> {
            if (currentCards == null && currentInfoCards == null) {
                Toast.makeText(this, "분석이 끝난 후 사용할 수 있습니다", Toast.LENGTH_SHORT).show();
                return;
            }
            String nid = currentAnalyzedNoticeId.isEmpty()
                    ? (selectedNotice != null ? selectedNotice.noticeId : "")
                    : currentAnalyzedNoticeId;
            NoticeChecklistDialog.show(this, BASE_URL,
                    currentUserId.isEmpty() ? DEFAULT_PARENT_ID : currentUserId,
                    nid, currentCards, currentInfoCards, selectedLanguage);
        });
        thisChecklistBtn.setVisibility(View.GONE);
        thisChecklistBtn.setTag("thisChecklistBtn");
        content.addView(thisChecklistBtn);

        // QR/신청 링크 — URL 있을 때만 표시. bottomActionsBar와 별도.
        linkSideTabButton = bottomLinkButton("🔗  신청 · QR", v -> showLinkActionsDialog());
        linkSideTabButton.setVisibility(View.GONE);
        LinearLayout.LayoutParams linkContentLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(52));
        linkContentLp.setMargins(dp(16), dp(4), dp(16), dp(4));
        content.addView(linkSideTabButton, linkContentLp);

        // 닫기
        content.addView(outlineButton("← " + uiText("back_to_notice"), v -> showNoticeDetail(notice)));

        // refs to cards for visibility toggling
        easyKoCard.setTag("easyKoCard");
        transCard.setTag("transCard");
        checklistCard.setTag("checklistCard");
        glossaryWrap.setTag("glossaryWrap");
        statusCard.setTag("statusCard");

        outer.addView(scroll);
        bottomActionsBar = new LinearLayout(this);
        bottomActionsBar.setOrientation(LinearLayout.HORIZONTAL);
        bottomActionsBar.setGravity(Gravity.CENTER);
        bottomActionsBar.setVisibility(View.VISIBLE);  // 이번 주 할 일은 항상 표시
        bottomActionsBar.setPadding(0, 0, 0, 0);
        // 이번 주 할 일 — 항상 표시
        Button weeklyBtn = bottomLinkButton("📅  " + calLoc("이번 주 할 일","Việc tuần này","This week","本周任务","งานสัปดาห์นี้","Tugas minggu ini","Энэ долоо хоногийн даалгавар","Задачи недели","今週のタスク"), v -> {
            Intent wi = new Intent(this, ChecklistActivity.class);
            wi.putExtra(ChecklistActivity.EXTRA_PARENT_ID,
                    currentUserId.isEmpty() ? DEFAULT_PARENT_ID : currentUserId);
            wi.putExtra(ChecklistActivity.EXTRA_TARGET_LANG, selectedLanguage);
            startActivity(wi);
        });
        calendarActionButton = bottomLinkButton("🗓  " + calLoc("미니 달력","Lịch nhỏ","Mini Calendar","小日历","ปฏิทินขนาดเล็ก","Kalendar Mini","Жижиг хуанли","Мини-календарь","ミニカレンダー"), v -> showMiniCalendarDialog());
        calendarActionButton.setVisibility(View.GONE);  // 이벤트 있을 때만 표시
        LinearLayout.LayoutParams weeklyLp = new LinearLayout.LayoutParams(0, dp(56), 1);
        weeklyLp.setMargins(0, 0, dp(6), 0);
        LinearLayout.LayoutParams calendarLp = new LinearLayout.LayoutParams(0, dp(56), 1);
        calendarLp.setMargins(dp(6), 0, 0, 0);
        bottomActionsBar.addView(weeklyBtn, weeklyLp);
        bottomActionsBar.addView(calendarActionButton, calendarLp);
        FrameLayout.LayoutParams tabLp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, dp(56), Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        tabLp.setMargins(dp(20), 0, dp(20), dp(16));
        outer.addView(bottomActionsBar, tabLp);
        setContentView(outer);

        analyzeSelectedNotice();
    }

    private int langIndex(String code) {
        for (int i = 0; i < LANG_CODES.length; i++) {
            if (LANG_CODES[i].equals(code)) return i;
        }
        return 0;
    }

    private void analyzeSelectedNotice() {
        if (selectedNotice == null) return;
        if (analysisStatusText != null) {
            analysisStatusText.setText(uiText("analyzing_detail"));
        }
        toggleResultCards(false);

        JSONObject payload = new JSONObject();
        selectedLanguage = getSavedLanguage();
        try { payload.put("target_language", backendLanguageCode(selectedLanguage)); } catch (Exception ignored) {}
        // OCR 업로드 케이스: 보관해둔 ML Kit layout_json을 payload에 첨부 → backend가 highlights[] 채움.
        // PDF/HWP 업로드는 layout 정보 없으니 그대로 패스 (highlights 빈 리스트로 응답).
        String storedLayout = ocrLayoutByNoticeId.get(selectedNotice.noticeId);
        if (storedLayout != null && !storedLayout.isEmpty()) {
            try { payload.put("layout_json", new JSONArray(storedLayout)); } catch (Exception ignored) {}
        }
        postJson("/notice/analyze/" + selectedNotice.noticeId, payload, result -> {
            if (!result.error.isEmpty()) {
                if (analysisStatusText != null) {
                    String message = result.error.toLowerCase().contains("timed out")
                            ? uiText("timeout")
                            : uiText("server_error") + "\n" + result.error;
                    analysisStatusText.setText(message);
                    ((View) analysisStatusText.getParent()).setVisibility(View.VISIBLE);
                }
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                JSONObject data = json.optJSONObject("data");
                if (data == null) {
                    if (analysisStatusText != null) analysisStatusText.setText("분석 결과가 없습니다.");
                    return;
                }
                applyAnalysis(data);
            } catch (Exception error) {
                if (analysisStatusText != null)
                    analysisStatusText.setText("응답 파싱 실패\n" + result.body);
            }
        });
    }

    private void applyAnalysis(JSONObject data) {
        StringBuilder koBuilder = new StringBuilder();
        StringBuilder trBuilder = new StringBuilder();
        StringBuilder easyBuilder = new StringBuilder();

        JSONArray cards = data.optJSONArray("cards");
        currentCards = cards;
        currentInfoCards = data.optJSONArray("info_cards");
        currentAnalyzedNoticeId = data.optString("notice_id", "");
        currentAnalysisItems = sortItemsByImportance(data.optJSONArray("items"));
        if (selectedNotice != null && !selectedNotice.text.isEmpty()) {
            String[] lines = selectedNotice.text.split("\n");
            currentNoticeTitle = lines[0].trim();
        } else {
            currentNoticeTitle = "";
        }
        String extractedTitle = data.optString("title", "");
        if (!extractedTitle.isEmpty()) currentNoticeTitle = extractedTitle;
        currentNoticeTitleTranslated = data.optString("title_translated", "");

        // 헤더 갱신 — heuristic 결과로 첫 줄 fallback 덮어쓰기 + 번역 부제 표시
        if (noticeTitleView != null && !extractedTitle.isEmpty()) {
            noticeTitleView.setText(extractedTitle);
        }
        boolean showSub = !currentNoticeTitleTranslated.isEmpty()
                && !"ko".equals(selectedLanguage) && !"ko_easy".equals(selectedLanguage);
        if (noticeTitleSubView != null && noticeTitleLangChip != null) {
            if (showSub) {
                noticeTitleLangChip.setText("🌐  " + languageDisplayName(selectedLanguage));
                noticeTitleLangChip.setVisibility(View.VISIBLE);
                noticeTitleSubView.setText(currentNoticeTitleTranslated);
                noticeTitleSubView.setVisibility(View.VISIBLE);
            } else {
                noticeTitleLangChip.setVisibility(View.GONE);
                noticeTitleSubView.setVisibility(View.GONE);
            }
        }

        if (cards != null && cards.length() > 0) {
            appendCardLines(cards, koBuilder, easyBuilder, trBuilder);
        } else {
            // fallback: deprecated items 구조
            if (currentAnalysisItems != null) {
                for (int i = 0; i < currentAnalysisItems.length(); i++) {
                    JSONObject item = currentAnalysisItems.optJSONObject(i);
                    if (item == null) continue;
                    appendItemLine(koBuilder, item, true);
                    appendItemLine(trBuilder, item, false);
                }
            }
        }

        String checklist = koBuilder.toString().trim();
        String translation = trBuilder.toString().trim();
        String easyKo = easyBuilder.toString().trim();

        if (checklistText != null && !checklist.isEmpty()) {
            checklistText.setText(checklist);
            ((View) checklistText.getParent()).setVisibility(View.VISIBLE);
        }
        if (translationText != null) {
            if (!selectedLanguage.equals("ko_easy") && !translation.isEmpty()) {
                translationText.setText(translation);
                translationText.setTextColor(COLOR_INK);
                ((View) translationText.getParent()).setVisibility(View.VISIBLE);
            }
        }

        // === 쉬운 한국어 (UI 숨김) ===
        // 세종님 제안 (2026-05-06): easy_korean 변환이 한두 단어 바꾸는 정도라 자리만
        // 차지함. 기능/응답 필드는 그대로 두고 화면 표시만 숨김. TTS 듣기 버튼도 함께
        // GONE 처리. 향후 easy_korean quality 향상 시 visibility 다시 풀면 됨.
        if (easyKoText != null) {
            easyKoText.setText(easyKo);
            ((View) easyKoText.getParent()).setVisibility(View.GONE);
        }

        // === summary 슬롯: 카테고리별 칩 (urls/phones 포함) ===
        if (!renderCardChips(cards)) {
            renderSummarySlots(data.optJSONObject("summary"));
        }
        renderLinkActions(data, cards);
        renderCalendarActions(data);

        // === TTS ===
        currentTtsUrl = optStringDeep(data, "tts_url", "tts_path", "audio_url");
        if (playButton != null && !selectedLanguage.equals("ko_easy") && !currentTtsUrl.isEmpty()) {
            playButton.setText(ttsLabel());
            playButton.setVisibility(View.VISIBLE);
        }
        currentEasyKoTtsUrl = optStringDeep(data, "tts_url_easy_ko");
        // 쉬운 한국어 텍스트 카드는 숨겼지만 듣기 버튼은 살림 — 한국어 발음 학습용
        // 도구로 의미 있음. 텍스트 안 보여도 음성 재생 OK.
        if (easyKoPlayButton != null && !currentEasyKoTtsUrl.isEmpty()) {
            easyKoPlayButton.setText(easyKoTtsLabel());
            easyKoPlayButton.setVisibility(View.VISIBLE);
        }
        boolean hasTts = (playButton != null && playButton.getVisibility() == View.VISIBLE)
                || (easyKoPlayButton != null && easyKoPlayButton.getVisibility() == View.VISIBLE);
        View speedRow = playButton != null ? findTaggedSibling(playButton, "speedRow") : null;
        if (speedRow != null) speedRow.setVisibility(hasTts ? View.VISIBLE : View.GONE);

        // status hide
        if (analysisStatusText != null) {
            View statusCard = (View) analysisStatusText.getParent();
            statusCard.setVisibility(View.GONE);
        }
    }

    private JSONArray sortItemsByImportance(JSONArray items) {
        if (items == null || items.length() <= 1) return items;
        List<JSONObject> list = new ArrayList<>();
        for (int i = 0; i < items.length(); i++) {
            JSONObject it = items.optJSONObject(i);
            if (it != null) list.add(it);
        }
        // importance 내림차순 (없으면 0.5)
        list.sort((a, b) -> Double.compare(
                b.optDouble("importance", 0.5),
                a.optDouble("importance", 0.5)));
        JSONArray out = new JSONArray();
        for (JSONObject it : list) out.put(it);
        return out;
    }

    private void appendCardLines(JSONArray cards, StringBuilder koBuilder,
                                 StringBuilder easyBuilder, StringBuilder trBuilder) {
        for (int i = 0; i < cards.length(); i++) {
            JSONObject card = cards.optJSONObject(i);
            if (card == null) continue;

            appendSlotCardLine(
                    koBuilder,
                    safeString(card, "header_ko"),
                    safeString(card, "value_ko"),
                    safeString(card, "chip")
            );
            appendSlotCardLine(
                    easyBuilder,
                    safeString(card, "header_ko"),
                    firstNonBlank(safeString(card, "value_easy_ko"), safeString(card, "value_ko")),
                    safeString(card, "chip")
            );
            appendSlotCardLine(
                    trBuilder,
                    firstNonBlank(safeString(card, "header_translated"), safeString(card, "header_ko")),
                    firstNonBlank(safeString(card, "value_translated"), safeString(card, "value_ko")),
                    safeString(card, "chip")
            );
        }
    }

    private void appendSlotCardLine(StringBuilder sb, String header, String value, String chip) {
        if (value.isEmpty()) return;
        // chip prefix는 별도 카드 chip 영역(renderCardChips)에서 표시되므로 본문에 중복 X
        // header가 "기타"면 의미 없는 슬롯 라벨이라 skip — 의미 있는 헤더("일시"/"마감"/"준비물" 등)만 유지
        if (!header.isEmpty() && !"기타".equals(header)) sb.append(header).append(": ");
        // 카드 사이 빈 줄 — 가독성 개선
        sb.append(value).append("\n\n");
    }

    private void appendItemLine(StringBuilder sb, JSONObject item, boolean korean) {
        String title = safeString(item, korean ? "title_ko" : "title_translated");
        if (title.isEmpty()) return;
        String actionHint = safeString(item, "action_hint");
        String amount = safeString(item, "amount");
        String deadline = safeString(item, "deadline");
        if (!actionHint.isEmpty()) sb.append("[").append(actionHint).append("] ");
        sb.append(title);
        List<String> meta = new ArrayList<>();
        if (!amount.isEmpty()) meta.add(amount);
        if (!deadline.isEmpty()) meta.add(deadline);
        if (!meta.isEmpty()) sb.append(" · ").append(TextUtils.join(" · ", meta));
        sb.append('\n');
    }

    private void renderLinkActions(JSONObject data, JSONArray cards) {
        currentActionUrls.clear();
        if (linkActionsBox != null) {
            linkActionsBox.removeAllViews();
            linkActionsBox.setVisibility(View.GONE);
            View wrap = (View) linkActionsBox.getParent();
            if (wrap != null) wrap.setVisibility(View.GONE);
        }

        Set<String> urls = new LinkedHashSet<>();
        collectUrlsFromCards(urls, cards);
        collectUrlsFromCards(urls, data.optJSONArray("info_cards"));
        JSONObject summary = data.optJSONObject("summary");
        if (summary != null) collectUrlsFromSlots(urls, summary.optJSONArray("urls"));

        if (urls.isEmpty()) {
            if (linkSideTabButton != null) linkSideTabButton.setVisibility(View.GONE);
            updateBottomActionsBarVisibility();
            return;
        }

        for (String url : urls) {
            if (currentActionUrls.size() >= 3) break;
            currentActionUrls.add(url);
        }
        if (linkSideTabButton != null) linkSideTabButton.setVisibility(View.VISIBLE);
        updateBottomActionsBarVisibility();
    }

    private void renderCalendarActions(JSONObject data) {
        currentCalendarEvents = data.optJSONArray("calendar_events");
        boolean hasEvents = currentCalendarEvents != null && currentCalendarEvents.length() > 0;
        if (calendarActionButton != null) {
            calendarActionButton.setVisibility(hasEvents ? View.VISIBLE : View.GONE);
        }
        updateBottomActionsBarVisibility();
    }

    private void updateBottomActionsBarVisibility() {
        if (bottomActionsBar == null) return;
        // 이번 주 할 일 버튼이 항상 있으므로 bottomActionsBar는 항상 visible
        bottomActionsBar.setVisibility(View.VISIBLE);
    }

    private void collectUrlsFromCards(Set<String> out, JSONArray cards) {
        if (cards == null) return;
        for (int i = 0; i < cards.length(); i++) {
            JSONObject card = cards.optJSONObject(i);
            if (card == null) continue;
            String header = safeString(card, "header_ko") + " " + safeString(card, "header_translated");
            String body = safeString(card, "value_ko") + " " + safeString(card, "value_translated");
            if (header.toLowerCase(Locale.ROOT).contains("url")
                    || header.contains("신청")
                    || URL_PATTERN.matcher(body).find()) {
                collectUrlsFromText(out, body);
            }
        }
    }

    private void collectUrlsFromSlots(Set<String> out, JSONArray slots) {
        if (slots == null) return;
        for (int i = 0; i < slots.length(); i++) {
            JSONObject slot = slots.optJSONObject(i);
            if (slot == null) continue;
            collectUrlsFromText(out, safeString(slot, "ko"));
            collectUrlsFromText(out, safeString(slot, "translated"));
        }
    }

    private void collectUrlsFromText(Set<String> out, String text) {
        if (text == null || text.isEmpty()) return;
        Matcher matcher = URL_PATTERN.matcher(text);
        while (matcher.find()) {
            String normalized = normalizeUrl(matcher.group());
            if (!normalized.isEmpty()) out.add(normalized);
        }
    }

    private String normalizeUrl(String url) {
        if (url == null) return "";
        String s = url.trim();
        while (s.endsWith(".") || s.endsWith(",") || s.endsWith(")") || s.endsWith("]")) {
            s = s.substring(0, s.length() - 1).trim();
        }
        if (s.startsWith("www.")) s = "https://" + s;
        if (!s.startsWith("http://") && !s.startsWith("https://")) return "";
        return s;
    }

    private LinearLayout linkActionBlock(String url, int index) {
        LinearLayout block = new LinearLayout(this);
        block.setOrientation(LinearLayout.VERTICAL);
        block.setPadding(0, index == 1 ? 0 : dp(12), 0, dp(8));

        TextView label = text(url, 13, COLOR_INK, false);
        label.setLineSpacing(0, 1.25f);
        label.setPadding(0, 0, 0, dp(8));
        block.addView(label);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);

        Button open = outlineButton("바로가기", v -> openExternalUrl(url));
        Button qr = outlineButton("QR 크게 보기", v -> showQrDialog(url));
        LinearLayout.LayoutParams openLp = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        openLp.setMargins(0, 0, dp(6), 0);
        LinearLayout.LayoutParams qrLp = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        qrLp.setMargins(dp(6), 0, 0, 0);
        row.addView(open, openLp);
        row.addView(qr, qrLp);
        block.addView(row);

        ImageView qrImage = new ImageView(this);
        LinearLayout.LayoutParams qlp = new LinearLayout.LayoutParams(dp(132), dp(132));
        qlp.gravity = Gravity.CENTER_HORIZONTAL;
        qlp.setMargins(0, dp(8), 0, 0);
        qrImage.setLayoutParams(qlp);
        qrImage.setBackgroundColor(Color.WHITE);
        qrImage.setPadding(dp(6), dp(6), dp(6), dp(6));
        block.addView(qrImage);
        loadQrImage(url, qrImage);

        return block;
    }

    private void openExternalUrl(String url) {
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            startActivity(intent);
        } catch (Exception error) {
            Toast.makeText(this, "링크를 열 수 없습니다.", Toast.LENGTH_SHORT).show();
        }
    }

    private void showQrDialog(String url) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(18), dp(12), dp(18), dp(4));

        TextView label = text(url, 13, COLOR_INK, false);
        label.setLineSpacing(0, 1.25f);
        label.setPadding(0, 0, 0, dp(10));
        box.addView(label);

        ImageView image = new ImageView(this);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(240), dp(240));
        lp.gravity = Gravity.CENTER_HORIZONTAL;
        image.setLayoutParams(lp);
        image.setBackgroundColor(Color.WHITE);
        image.setPadding(dp(8), dp(8), dp(8), dp(8));
        box.addView(image);
        loadQrImage(url, image);

        new AlertDialog.Builder(this)
                .setTitle("신청 QR 코드")
                .setView(box)
                .setPositiveButton("바로가기", (d, w) -> openExternalUrl(url))
                .setNegativeButton("닫기", null)
                .show();
    }

    private void showLinkActionsDialog() {
        if (currentActionUrls.isEmpty()) return;

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(18), dp(12), dp(18), dp(4));

        TextView intro = text("신청 URL을 열거나 QR 코드로 공유할 수 있습니다.", 13, COLOR_INK2, false);
        intro.setLineSpacing(0, 1.3f);
        intro.setPadding(0, 0, 0, dp(8));
        box.addView(intro);

        for (int i = 0; i < currentActionUrls.size(); i++) {
            box.addView(linkActionBlock(currentActionUrls.get(i), i + 1));
        }

        new AlertDialog.Builder(this)
                .setTitle("신청 바로가기")
                .setView(box)
                .setNegativeButton("닫기", null)
                .show();
    }

    private void showMiniCalendarDialog() {
        if (currentCalendarEvents == null || currentCalendarEvents.length() == 0) return;
        Calendar month = Calendar.getInstance();
        Date firstDate = parseIsoDate(safeString(currentCalendarEvents.optJSONObject(0), "start_date"));
        if (firstDate != null) month.setTime(firstDate);
        month.set(Calendar.DAY_OF_MONTH, 1);
        showMiniCalendarForMonth(month);
    }

    private void showMiniCalendarForMonth(Calendar month) {
        AlertDialog[] holder = {null};

        ScrollView scroll = new ScrollView(this);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(14), dp(10), dp(14), dp(4));
        scroll.addView(box);

        // ── 이전/다음 달 내비게이션 ──
        Calendar prevMonth = (Calendar) month.clone();
        prevMonth.add(Calendar.MONTH, -1);
        Calendar nextMonth = (Calendar) month.clone();
        nextMonth.add(Calendar.MONTH, 1);

        LinearLayout navRow = new LinearLayout(this);
        navRow.setOrientation(LinearLayout.HORIZONTAL);
        navRow.setGravity(Gravity.CENTER_VERTICAL);

        TextView prevBtn = text("◀", 16, COLOR_INK2, true);
        prevBtn.setPadding(dp(10), dp(6), dp(10), dp(6));
        prevBtn.setOnClickListener(v -> {
            if (holder[0] != null) holder[0].dismiss();
            showMiniCalendarForMonth(prevMonth);
        });

        TextView monthTitle = text(
                new SimpleDateFormat("yyyy년 M월", Locale.KOREA).format(month.getTime()),
                17, COLOR_INK, true);
        monthTitle.setGravity(Gravity.CENTER);
        monthTitle.setLayoutParams(new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        TextView nextBtn = text("▶", 16, COLOR_INK2, true);
        nextBtn.setPadding(dp(10), dp(6), dp(10), dp(6));
        nextBtn.setOnClickListener(v -> {
            if (holder[0] != null) holder[0].dismiss();
            showMiniCalendarForMonth(nextMonth);
        });

        navRow.addView(prevBtn);
        navRow.addView(monthTitle);
        navRow.addView(nextBtn);
        LinearLayout.LayoutParams navLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        navLp.bottomMargin = dp(6);
        navRow.setLayoutParams(navLp);
        box.addView(navRow);

        // ── 범례 ──
        LinearLayout legend = new LinearLayout(this);
        legend.setOrientation(LinearLayout.HORIZONTAL);
        legend.setGravity(Gravity.CENTER);
        legend.addView(calendarLegend(calLoc("신청","Đăng ký","Register","报名","การสมัคร","Daftar","Бүртгэл","Запись","申込"), calendarColor("blue")));
        legend.addView(calendarLegend(calLoc("행사","Sự kiện","Event","活动","กิจกรรม","Acara","Арга хэмжээ","Мероприятие","行事"), calendarColor("green")));
        legend.addView(calendarLegend(calLoc("제출","Nộp","Submit","提交","ส่งเอกสาร","Hantar","Илгээх","Сдача","提出"), calendarColor("orange")));
        legend.addView(calendarLegend(calLoc("비용/납부","Chi phí","Fee","费用","ค่าใช้จ่าย","Yuran","Төлбөр","Оплата","費用"), calendarColor("gold")));
        legend.addView(calendarLegend(calLoc("휴업/기념일","Nghỉ lễ","Holiday","休假","วันหยุด","Cuti","Амралт","Праздник","休日"), calendarColor("red")));
        box.addView(legend);

        // ── 요일 헤더 ──
        LinearLayout weekHeader = new LinearLayout(this);
        weekHeader.setOrientation(LinearLayout.HORIZONTAL);
        String[] days = calDays();
        for (String d : days) {
            TextView day = text(d, 11, "일".equals(d) ? calendarColor("red") : COLOR_INK3, true);
            day.setGravity(Gravity.CENTER);
            weekHeader.addView(day, new LinearLayout.LayoutParams(0, dp(24), 1));
        }
        box.addView(weekHeader);

        // ── 날짜 그리드 ──
        int firstDow = month.get(Calendar.DAY_OF_WEEK) - 1;
        int maxDay = month.getActualMaximum(Calendar.DAY_OF_MONTH);
        int dayNum = 1;
        for (int row = 0; row < 6; row++) {
            LinearLayout week = new LinearLayout(this);
            week.setOrientation(LinearLayout.HORIZONTAL);
            for (int col = 0; col < 7; col++) {
                LinearLayout cell = calendarDayCell();
                if (!(row == 0 && col < firstDow) && dayNum <= maxDay) {
                    Calendar dayCal = (Calendar) month.clone();
                    dayCal.set(Calendar.DAY_OF_MONTH, dayNum);
                    String iso = new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(dayCal.getTime());
                    JSONArray dayEvents = eventsForDate(iso);
                    TextView num = text(String.valueOf(dayNum),
                            12,
                            hasRedCalendarEvent(dayEvents) || col == 0 ? calendarColor("red") : COLOR_INK,
                            true);
                    num.setGravity(Gravity.CENTER);
                    cell.addView(num);
                    addCalendarMarkers(cell, dayEvents);
                    final String selectedIso = iso;
                    final JSONArray selectedEvents = dayEvents;
                    if (dayEvents.length() > 0) {
                        cell.setOnClickListener(v -> showCalendarDayDialog(selectedIso, selectedEvents));
                    }
                    dayNum++;
                }
                week.addView(cell, new LinearLayout.LayoutParams(0, dp(58), 1));
            }
            box.addView(week);
            if (dayNum > maxDay) break;
        }

        // ── 안내 텍스트 ──
        TextView guide = text("기간은 작대기, 하루 일정은 점으로 표시됩니다. 날짜를 누르면 원문 카드로 확인할 수 있어요.",
                12, COLOR_INK3, false);
        guide.setLineSpacing(0, 1.25f);
        guide.setPadding(0, dp(10), 0, 0);
        box.addView(guide);

        holder[0] = new AlertDialog.Builder(this)
                .setTitle(calLoc("미니 달력","Lịch nhỏ","Mini Calendar","小日历","ปฏิทินขนาดเล็ก","Kalendar Mini","Жижиг хуанли","Мини-календарь","ミニカレンダー"))
                .setView(scroll)
                .setNegativeButton(calLoc("닫기","Đóng","Close","关闭","ปิด","Tutup","Хаах","Закрыть","閉じる"), null)
                .show();
    }

    private LinearLayout calendarDayCell() {
        LinearLayout cell = new LinearLayout(this);
        cell.setOrientation(LinearLayout.VERTICAL);
        cell.setGravity(Gravity.TOP | Gravity.CENTER_HORIZONTAL);
        cell.setPadding(dp(2), dp(4), dp(2), dp(2));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(8));
        bg.setStroke(dp(1), Color.parseColor("#F1E4D4"));
        cell.setBackground(bg);
        return cell;
    }

    private TextView calendarLegend(String label, int color) {
        TextView view = text("● " + label + "  ", 10, color, true);
        view.setSingleLine(true);
        return view;
    }

    private String calLoc(String ko, String vi, String en, String zh,
                          String th, String ms, String mn, String ru, String ja) {
        switch (selectedLanguage) {
            case "vi": return vi;
            case "en": return en;
            case "zh": return zh;
            case "th": return th;
            case "ms": return ms;
            case "mn": return mn;
            case "ru": return ru;
            case "ja": return ja;
            default:   return ko;
        }
    }

    private String calEventLabel(String ko) {
        switch (ko) {
            case "운영일시":  return calLoc("운영일시","Ngày và giờ","Date & Time","日期与时间","วันและเวลา","Tarikh & Masa","Огноо цаг","Дата и время","日時");
            case "신청기간":  return calLoc("신청기간","Thời hạn đăng ký","Registration","报名期间","ช่วงสมัคร","Tempoh daftar","Бүртгэлийн хугацаа","Период записи","申込期間");
            case "제출기한":  return calLoc("제출기한","Hạn nộp","Submission deadline","提交截止","กำหนดส่ง","Tarikh hantar","Хүргэх хугацаа","Срок сдачи","提出期限");
            case "납부기한":  return calLoc("납부기한","Hạn thanh toán","Payment deadline","缴费截止","กำหนดชำระ","Tarikh bayar","Төлбөрийн хугацаа","Срок оплаты","納付期限");
            case "일정":     return calLoc("일정","Lịch","Schedule","日程","ตาราง","Jadual","Хуваарь","Расписание","日程");
            case "휴업/기념일": return calLoc("휴업/기념일","Nghỉ lễ","Holiday","休假/纪念日","วันหยุด","Cuti","Амралт","Праздник","休日");
            default:         return ko;
        }
    }

    private String[] calDays() {
        switch (selectedLanguage) {
            case "vi": return new String[]{"CN","T2","T3","T4","T5","T6","T7"};
            case "en": return new String[]{"Su","Mo","Tu","We","Th","Fr","Sa"};
            case "zh": return new String[]{"日","一","二","三","四","五","六"};
            case "ja": return new String[]{"日","月","火","水","木","金","土"};
            default:   return new String[]{"일","월","화","수","목","금","토"};
        }
    }

    private void addCalendarMarkers(LinearLayout cell, JSONArray events) {
        int added = 0;
        for (int i = 0; i < events.length() && added < 3; i++) {
            JSONObject event = events.optJSONObject(i);
            if (event == null) continue;
            boolean period = isPeriodEvent(event);
            TextView marker = text(period ? "━━━━" : "●", period ? 9 : 12,
                    calendarColor(safeString(event, "color")), true);
            marker.setGravity(Gravity.CENTER);
            marker.setSingleLine(true);
            cell.addView(marker);
            added++;
        }
    }

    private JSONArray eventsForDate(String isoDate) {
        JSONArray out = new JSONArray();
        if (currentCalendarEvents == null) return out;
        Date day = parseIsoDate(isoDate);
        if (day == null) return out;
        for (int i = 0; i < currentCalendarEvents.length(); i++) {
            JSONObject event = currentCalendarEvents.optJSONObject(i);
            if (event == null) continue;
            Date start = parseIsoDate(safeString(event, "start_date"));
            Date end = parseIsoDate(firstNonBlank(safeString(event, "end_date"), safeString(event, "start_date")));
            if (start == null || end == null) continue;
            if (!day.before(start) && !day.after(end)) out.put(event);
        }
        return out;
    }

    private void showCalendarDayDialog(String isoDate, JSONArray events) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(16), dp(10), dp(16), dp(4));
        for (int i = 0; i < events.length(); i++) {
            JSONObject event = events.optJSONObject(i);
            if (event == null) continue;
            box.addView(calendarEventBlock(event));
        }
        String calTitle = isoDate + " " + calLoc("일정","lịch","schedule","日程","ตาราง","jadual","хуваарь","расписание","日程");
        String calClose = calLoc("닫기","Đóng","Close","关闭","ปิด","Tutup","Хаах","Закрыть","閉じる");
        new AlertDialog.Builder(this)
                .setTitle(calTitle)
                .setView(box)
                .setNegativeButton(calClose, null)
                .show();
    }

    private LinearLayout calendarEventBlock(JSONObject event) {
        LinearLayout block = new LinearLayout(this);
        block.setOrientation(LinearLayout.VERTICAL);
        block.setPadding(0, 0, 0, dp(12));
        String rawLabel = firstNonBlank(safeString(event, "label"), safeString(event, "type"));
        TextView label = text("● " + calEventLabel(rawLabel), 13, calendarColor(safeString(event, "color")), true);
        boolean isKo = "ko".equals(selectedLanguage) || "ko_easy".equals(selectedLanguage);
        String bodyStr = isKo
                ? firstNonBlank(safeString(event, "display_text"), safeString(event, "source_text"))
                : firstNonBlank(safeString(event, "translated"), safeString(event, "display_text"), safeString(event, "source_text"));
        TextView body = text(bodyStr, 13, COLOR_INK, false);
        body.setLineSpacing(0, 1.35f);
        block.addView(label);
        block.addView(body);

        JSONArray actions = event.optJSONArray("actions");
        String url = firstUrlAction(actions);
        if (!url.isEmpty()) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            Button open = outlineButton("바로가기", v -> openExternalUrl(url));
            Button qr = outlineButton("QR 보기", v -> showQrDialog(url));
            row.addView(open, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
            row.addView(qr, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
            block.addView(row);
        }
        return block;
    }

    private String firstUrlAction(JSONArray actions) {
        if (actions == null) return "";
        for (int i = 0; i < actions.length(); i++) {
            JSONObject action = actions.optJSONObject(i);
            if (action == null) continue;
            String type = safeString(action, "type");
            if ("open_url".equals(type) || "show_qr".equals(type)) {
                return normalizeUrl(safeString(action, "value"));
            }
        }
        return "";
    }

    private boolean isPeriodEvent(JSONObject event) {
        String start = safeString(event, "start_date");
        String end = safeString(event, "end_date");
        return !end.isEmpty() && !end.equals(start);
    }

    private boolean hasRedCalendarEvent(JSONArray events) {
        for (int i = 0; i < events.length(); i++) {
            JSONObject event = events.optJSONObject(i);
            if (event != null && "red".equals(safeString(event, "color"))) return true;
        }
        return false;
    }

    private Date parseIsoDate(String iso) {
        if (iso == null || iso.trim().isEmpty()) return null;
        try {
            return new SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(iso.trim());
        } catch (Exception ignored) {
            return null;
        }
    }

    private int calendarColor(String color) {
        switch ((color == null ? "" : color).toLowerCase(Locale.ROOT)) {
            case "blue": return Color.parseColor("#2F80ED");
            case "green": return Color.parseColor("#2F9E6D");
            case "orange": return Color.parseColor("#F2994A");
            case "gold": return Color.parseColor("#D4A017");
            case "red": return Color.parseColor("#D64545");
            case "purple": return Color.parseColor("#7B61D1");
            default: return COLOR_INK3;
        }
    }

    private void loadQrImage(String url, ImageView image) {
        executor.execute(() -> {
            Bitmap bmp = null;
            try {
                String encoded = URLEncoder.encode(url, "UTF-8");
                URL qrUrl = new URL("https://quickchart.io/qr?size=320&margin=2&text=" + encoded);
                HttpURLConnection conn = (HttpURLConnection) qrUrl.openConnection();
                conn.setConnectTimeout(8000);
                conn.setReadTimeout(12000);
                try (InputStream is = conn.getInputStream()) {
                    bmp = BitmapFactory.decodeStream(is);
                } finally {
                    conn.disconnect();
                }
            } catch (Exception ignored) {
                bmp = null;
            }
            final Bitmap fbmp = bmp;
            runOnUiThread(() -> {
                if (fbmp != null) image.setImageBitmap(fbmp);
                else image.setVisibility(View.GONE);
            });
        });
    }

    private boolean renderCardChips(JSONArray cards) {
        // 세종님 제안 (2026-05-06): "📖 사용된 학교 용어" 박스가 사실은 카드 chip 을
        // 재활용해서 표시 중이라 라벨/기능 매핑 어긋남. backend 에 glossary_hits 응답
        // 추가하기 전엔 숨기는 게 깔끔. 함수는 남겨두고 visibility 만 강제 GONE.
        if (glossaryChipsBox != null) {
            View parent = (View) glossaryChipsBox.getParent();
            if (parent != null) parent.setVisibility(View.GONE);
        }
        return false;
    }

    private String chipIcon(String chip) {
        if (chip.contains("일정")) return "📅";
        if (chip.contains("준비")) return "📦";
        if (chip.contains("제출")) return "📝";
        if (chip.contains("비용")) return "💰";
        if (chip.contains("건강") || chip.contains("안전")) return "🛡";
        return "📌";
    }

    private void renderSummarySlots(JSONObject summary) {
        if (summary == null || glossaryChipsBox == null) return;
        glossaryChipsBox.removeAllViews();
        int added = 0;
        added += addSlotChips(glossaryChipsBox, summary.optJSONArray("dates"),    "📅");
        added += addSlotChips(glossaryChipsBox, summary.optJSONArray("times"),    "⏰");
        added += addSlotChips(glossaryChipsBox, summary.optJSONArray("amounts"),  "💰");
        added += addSlotChips(glossaryChipsBox, summary.optJSONArray("places"),   "📍");
        added += addSlotChips(glossaryChipsBox, summary.optJSONArray("supplies"), "📦");
        added += addSlotChips(glossaryChipsBox, summary.optJSONArray("deadlines"),"⌛");
        // urls/phones는 NLLB 번역 안 거치고 한국어 그대로 — 신뢰도 표시용
        added += addSlotChips(glossaryChipsBox, summary.optJSONArray("urls"),     "🔗");
        added += addSlotChips(glossaryChipsBox, summary.optJSONArray("phones"),   "☎");
        // glossaryWrap 은 숨김 유지 — "사용된 학교 용어" 박스 미표시 결정
    }

    private int addSlotChips(LinearLayout box, JSONArray slots, String icon) {
        if (slots == null || slots.length() == 0) return 0;
        int count = 0;
        for (int i = 0; i < slots.length() && count < 4; i++) {  // 슬롯 종류당 최대 4개
            JSONObject slot = slots.optJSONObject(i);
            if (slot == null) continue;
            String ko = safeString(slot, "ko");
            String translated = safeString(slot, "translated");
            if (ko.isEmpty()) continue;
            String tgt = translated.equals(ko) ? "" : translated;  // 같으면 한국어만 표시
            box.addView(slotChipRow(icon, ko, tgt));
            count++;
        }
        return count;
    }

    private LinearLayout slotChipRow(String icon, String ko, String translated) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(4), 0, dp(4));
        TextView ic = text(icon, 14, COLOR_LEMON_INK, true);
        ic.setPadding(0, 0, dp(8), 0);
        row.addView(ic);
        String label = translated.isEmpty() ? ko : ko + "  →  " + translated;
        TextView t = text(label, 13, COLOR_INK, false);
        row.addView(t);
        return row;
    }

    private LinearLayout glossaryChipRow(String ko, String tgt) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(4), 0, dp(4));
        TextView k = text(ko, 13, COLOR_LEMON_INK, true);
        row.addView(k);
        TextView arrow = text("  →  ", 12, COLOR_LEMON_INK, false);
        arrow.setAlpha(0.6f);
        row.addView(arrow);
        TextView t = text(tgt, 13, COLOR_LEMON_INK, false);
        row.addView(t);
        return row;
    }

    private void toggleResultCards(boolean show) {
        if (content == null) return;
        for (int i = 0; i < content.getChildCount(); i++) {
            View v = content.getChildAt(i);
            Object tag = v.getTag();
            if (tag == null) continue;
            String s = tag.toString();
            if (s.equals("easyKoCard") || s.equals("transCard")
                    || s.equals("checklistCard") || s.equals("glossaryWrap")
                    || s.equals("thisChecklistBtn")) {
                v.setVisibility(show ? View.VISIBLE : View.GONE);
            }
        }
    }

    private void showMockAnalysis() {
        if (checklistText != null) {
            checklistText.setText("✓  물병과 도시락 준비\n✓  오전 9시까지 학교 운동장 도착");
            ((View) checklistText.getParent()).setVisibility(View.VISIBLE);
        }
        if (easyKoText != null) {
            easyKoText.setText("내일 현장학습이 있습니다.\n아이는 물병과 도시락을 가져와 주세요.\n아침 9시까지 학교 운동장으로 와 주세요.");
            ((View) easyKoText.getParent()).setVisibility(View.VISIBLE);
        }
        if (translationText != null) {
            String t;
            switch (selectedLanguage) {
                case "vi":
                    t = "Ngày mai có dã ngoại học tập. Hãy chuẩn bị cơm hộp và bình nước cho con.\nĐến sân vận động trường lúc 9 giờ sáng.";
                    break;
                case "en":
                    t = "There is a field trip tomorrow. Please pack a lunchbox and water bottle.\nArrive at the school playground by 9 AM.";
                    break;
                default:
                    t = "(오프라인 데모 — 베트남어/영어만 미리 준비됨)";
            }
            translationText.setText(t);
            ((View) translationText.getParent()).setVisibility(View.VISIBLE);
        }
        if (playButton != null) playButton.setVisibility(View.VISIBLE);
        if (analysisStatusText != null) {
            View statusCard = (View) analysisStatusText.getParent();
            statusCard.setVisibility(View.GONE);
        }
    }

    // 분석 결과 본문에 학교 용어 lemon highlight
    private CharSequence highlightGlossary(String text, String qualityNote) {
        SpannableString span = new SpannableString(text);
        if (TextUtils.isEmpty(qualityNote) || TextUtils.isEmpty(text)) return span;
        for (String pair : qualityNote.split("[;\n]")) {
            String[] parts = pair.split("->");
            if (parts.length < 2) continue;
            String tgt = parts[1].trim();
            if (tgt.length() < 2) continue;
            int idx = text.indexOf(tgt);
            while (idx != -1) {
                span.setSpan(new BackgroundColorSpan(COLOR_LEMON),
                        idx, idx + tgt.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                span.setSpan(new ForegroundColorSpan(COLOR_LEMON_INK),
                        idx, idx + tgt.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                idx = text.indexOf(tgt, idx + tgt.length());
            }
        }
        return span;
    }

    // ============================================================
    //  SEND NOTICE (선생님 발송)
    //  pendingFileBytes 있으면 → /notice/upload (파일 + 원본 보존, 학부모가 풀화면 PDF/이미지 조회)
    //  없으면 → /notice/send (텍스트 직송)
    // ============================================================
    private void sendNotice() {
        String title = safe(titleInput.getText().toString());
        String body = safe(bodyInput.getText().toString());
        final String teacherId = currentUserId;
        String parentIdRaw = safe(parentIdInput.getText().toString());
        final String parentId = parentIdRaw.isEmpty() ? DEFAULT_PARENT_ID : parentIdRaw;
        if (body.isEmpty()) {
            setSendResult("⚠️ 본문을 입력해주세요.", false);
            return;
        }

        // 파일 첨부된 경우 — /notice/upload로 발송 (원본 파일 보존)
        if (pendingFileBytes != null && pendingFilename != null) {
            final byte[] bytes = pendingFileBytes;
            final String filename = pendingFilename;
            setSendResult("📤 발송 중... (파일 첨부 " + filename + ")", true);
            executor.execute(() -> {
                ApiResult result = postMultipartUpload(teacherId, parentId, filename, bytes);
                runOnUiThread(() -> {
                    if (!result.error.isEmpty()) {
                        setSendResult("❌ 발송 실패: " + result.error, false);
                        return;
                    }
                    try {
                        JSONObject json = new JSONObject(result.body);
                        JSONObject d = json.optJSONObject("data");
                        String noticeId = safeString(d, "notice_id");
                        setSendResult("✅ 발송 완료 (파일 첨부)\n→ " + parentId
                                + " · #" + shorten(noticeId, 8), true);
                        // 발송 후 첨부 + 미리보기 클리어 (재발송 방지) + 텍스트 입력란 복귀
                        pendingFileBytes = null;
                        pendingFilename = null;
                        pendingPreviewUrl = null;
                        pendingPreviewMime = null;
                        if (teacherPreviewBox != null) {
                            teacherPreviewBox.removeAllViews();
                            teacherPreviewBox.setVisibility(View.GONE);
                        }
                        if (teacherTitleCard != null) teacherTitleCard.setVisibility(View.VISIBLE);
                        if (teacherBodyCard != null) teacherBodyCard.setVisibility(View.VISIBLE);
                        // 추출된 텍스트 클리어 — 발송 후 빈 입력란으로 복귀
                        if (titleInput != null) titleInput.setText("");
                        if (bodyInput != null) bodyInput.setText("");
                    } catch (Exception error) {
                        setSendResult("응답 파싱 실패\n" + result.body, false);
                    }
                });
            });
            return;
        }

        // 텍스트 직송
        String payloadText = title.isEmpty() ? body : title + "\n" + body;
        JSONObject bodyJson = new JSONObject();
        try {
            bodyJson.put("teacher_id", teacherId);
            bodyJson.put("parent_id", parentId);
            bodyJson.put("text", payloadText);
        } catch (Exception error) {
            setSendResult("오류: " + error.getMessage(), false);
            return;
        }

        setSendResult("📤 발송 중...", true);
        postJson("/notice/send", bodyJson, result -> {
            if (!result.error.isEmpty()) {
                setSendResult("❌ 서버 연결 실패: " + result.error, false);
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                JSONObject data = json.optJSONObject("data");
                String noticeId = safeString(data, "notice_id");
                setSendResult("✅ 발송 완료\n→ " + parentId + " · #" + shorten(noticeId, 8), true);
            } catch (Exception error) {
                setSendResult("응답 파싱 실패\n" + result.body, false);
            }
        });
    }

    private void setSendResult(String value, boolean success) {
        if (sendResultText == null) return;
        sendResultText.setVisibility(View.VISIBLE);
        sendResultText.setText(value);
        sendResultText.setTextColor(success ? COLOR_MINT_INK : Color.parseColor("#B33A3A"));
    }

    private void fillSampleNotice() {
        if (titleInput != null) titleInput.setText("현장학습 안내");
        if (bodyInput != null)  bodyInput.setText(sampleNotice());
        if (parentIdInput != null) parentIdInput.setText(DEFAULT_PARENT_ID);
    }

    // ============================================================
    //  파일 업로드 (HWP/PDF/TXT → /notice/upload)
    //  선생님 단말의 파일을 SAF로 선택해 multipart로 백엔드에 송신.
    // ============================================================
    private void launchFilePicker() {
        if (parentIdInput == null) return;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[] {
                "application/pdf",
                "application/x-hwp",
                "application/haansofthwp",
                "application/vnd.hancom.hwp",
                "application/octet-stream",
                "text/plain",
        });
        try {
            startActivityForResult(intent, REQUEST_PICK_FILE);
        } catch (Exception error) {
            setSendResult("❌ 파일 선택기를 열 수 없습니다: " + error.getMessage(), false);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_PICK_FILE) {
            if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
            Uri uri = data.getData();
            String filename = queryDisplayName(uri);
            long sizeBytes = querySize(uri);
            uploadSelectedFile(uri, filename, sizeBytes);
        } else if (requestCode == REQUEST_PICK_FILE_PARENT) {
            if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
            Uri uri = data.getData();
            String filename = queryDisplayName(uri);
            long sizeBytes = querySize(uri);
            uploadSelfFile(uri, filename, sizeBytes);
        } else if (requestCode == REQUEST_OCR) {
            if (resultCode != RESULT_OK || data == null) return;
            String noticeId  = data.getStringExtra(OcrActivity.RESULT_NOTICE_ID);
            int    charCount = data.getIntExtra(OcrActivity.RESULT_CHAR_COUNT, 0);
            String layoutJson = data.getStringExtra(OcrActivity.RESULT_OCR_LAYOUT);
            int bboxLineCount = countOcrLayoutLines(layoutJson);
            if (noticeId != null && !noticeId.isEmpty()
                    && layoutJson != null && bboxLineCount > 0) {
                ocrLayoutByNoticeId.put(noticeId, layoutJson);
            }
            setSendResult(
                    "✅ OCR 업로드 완료\n→ " + DEFAULT_PARENT_ID
                            + " · #" + shorten(noticeId != null ? noticeId : "", 8)
                            + " · 추출 " + charCount + "자"
                            + "\n→ bbox line " + bboxLineCount + "개",
                    true);
        }
    }

    private int countOcrLayoutLines(String layoutJson) {
        if (layoutJson == null || layoutJson.trim().isEmpty()) return 0;
        try {
            return new JSONArray(layoutJson).length();
        } catch (Exception ignored) {
            return 0;
        }
    }

    private void showUploadDialog() {
        new AlertDialog.Builder(this)
                .setTitle("통신문 올리기")
                .setItems(new String[]{"📷  사진으로 찍기", "📄  PDF 파일 올리기"}, (dialog, which) -> {
                    if (which == 0) launchOcrActivity();
                    else launchFilePickerParent();
                })
                .show();
    }

    private void launchFilePickerParent() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{
                "application/pdf",
                "text/plain",
        });
        try {
            startActivityForResult(intent, REQUEST_PICK_FILE_PARENT);
        } catch (Exception e) {
            Toast.makeText(this, "파일 선택기를 열 수 없습니다: " + e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }

    private void uploadSelfFile(Uri uri, String filename, long sizeBytes) {
        final String parentId = currentUserId.isEmpty() ? DEFAULT_PARENT_ID : currentUserId;
        String sizeLabel = sizeBytes > 0 ? " (" + (sizeBytes / 1024) + " KB)" : "";
        Toast.makeText(this, "📤 업로드 중... " + filename + sizeLabel, Toast.LENGTH_SHORT).show();

        executor.execute(() -> {
            byte[] bytes;
            try (InputStream is = getContentResolver().openInputStream(uri)) {
                if (is == null) throw new IOException("InputStream null");
                bytes = readAllBytes(is);
            } catch (Exception e) {
                String msg = e.getMessage() == null ? e.toString() : e.getMessage();
                runOnUiThread(() -> Toast.makeText(this, "❌ 파일 읽기 실패: " + msg, Toast.LENGTH_LONG).show());
                return;
            }

            ApiResult result = postMultipartUploadSelf(parentId, filename, bytes);
            runOnUiThread(() -> {
                if (!result.error.isEmpty()) {
                    Toast.makeText(this, "❌ 업로드 실패: " + result.error, Toast.LENGTH_LONG).show();
                    return;
                }
                try {
                    JSONObject json = new JSONObject(result.body);
                    JSONObject d = json.optJSONObject("data");
                    String noticeId = safeString(d, "notice_id");
                    int charCount = d == null ? 0 : d.optInt("char_count", 0);
                    Toast.makeText(this,
                            "✅ 업로드 완료 · #" + shorten(noticeId, 8) + " · " + charCount + "자",
                            Toast.LENGTH_LONG).show();
                    loadInbox();
                } catch (Exception e) {
                    Toast.makeText(this, "응답 파싱 실패\n" + result.body, Toast.LENGTH_LONG).show();
                }
            });
        });
    }

    private ApiResult postMultipartUploadSelf(String parentId, String filename, byte[] fileBytes) {
        ApiResult result = new ApiResult();
        HttpURLConnection conn = null;
        String boundary = "----DaonBoundary" + System.currentTimeMillis();
        try {
            URL url = new URL(BASE_URL + "/notice/upload-self");
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(30000);
            conn.setReadTimeout(180000);
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
            conn.setRequestProperty("X-User-Id", parentId);
            conn.setDoOutput(true);

            try (OutputStream os = conn.getOutputStream()) {
                writeMultipartField(os, boundary, "parent_id", parentId);
                writeMultipartFile(os, boundary, "file", filename, fileBytes);
                os.write(("--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
            }

            int code = conn.getResponseCode();
            InputStream stream = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
            result.body = readStream(stream);
            if (code < 200 || code >= 300) result.error = "HTTP " + code + "\n" + result.body;
        } catch (Exception e) {
            result.error = e.getMessage() == null ? e.toString() : e.getMessage();
        } finally {
            if (conn != null) conn.disconnect();
        }
        return result;
    }

    private void launchOcrActivity() {
        String parentIdRaw = parentIdInput == null ? "" : safe(parentIdInput.getText().toString());
        final String parentId = parentIdRaw.isEmpty() ? DEFAULT_PARENT_ID : parentIdRaw;
        Intent intent = new Intent(this, OcrActivity.class);
        intent.putExtra(OcrActivity.EXTRA_BASE_URL,   BASE_URL);
        intent.putExtra(OcrActivity.EXTRA_TEACHER_ID, currentUserId);
        intent.putExtra(OcrActivity.EXTRA_PARENT_ID,  parentId);
        startActivityForResult(intent, REQUEST_OCR);
    }

    private void uploadSelectedFile(Uri uri, String filename, long sizeBytes) {
        // 미리보기 모드: /notice/extract-text 호출 → 텍스트만 받아서 bodyInput에 표시
        // 실제 발송은 사용자가 발송 버튼 누를 때 (sendNotice() 분기에서 처리)
        String sizeLabel = sizeBytes > 0 ? " (" + (sizeBytes / 1024) + " KB)" : "";
        setSendResult("📄 미리보기 변환 중... " + filename + sizeLabel, true);

        executor.execute(() -> {
            byte[] bytes;
            try (InputStream is = getContentResolver().openInputStream(uri)) {
                if (is == null) throw new IOException("InputStream null");
                bytes = readAllBytes(is);
            } catch (Exception error) {
                String msg = error.getMessage() == null ? error.toString() : error.getMessage();
                runOnUiThread(() -> setSendResult("❌ 파일 읽기 실패: " + msg, false));
                return;
            }

            ApiResult result = postMultipartExtractText(filename, bytes);
            runOnUiThread(() -> {
                if (!result.error.isEmpty()) {
                    setSendResult("❌ 텍스트 추출 실패: " + result.error, false);
                    return;
                }
                try {
                    JSONObject json = new JSONObject(result.body);
                    JSONObject d = json.optJSONObject("data");
                    int charCount = d == null ? 0 : d.optInt("char_count", 0);
                    String extractedText = d == null ? "" : d.optString("text", "");
                    String previewUrl = d == null ? "" : d.optString("preview_file_url", "");
                    String previewMime = d == null ? "" : d.optString("preview_mime_type", "");
                    if (bodyInput != null) bodyInput.setText(extractedText);
                    if (titleInput != null) titleInput.setText("");
                    pendingFileBytes = bytes;
                    pendingFilename = filename;
                    pendingPreviewUrl = previewUrl.isEmpty() ? null : previewUrl;
                    pendingPreviewMime = previewMime.isEmpty() ? null : previewMime;
                    // 선생님 화면에 PDF/이미지 미리보기 카드 추가 + 텍스트 입력란 숨기기
                    if (pendingPreviewUrl != null && teacherPreviewBox != null) {
                        teacherPreviewBox.removeAllViews();
                        NoticeItem previewItem = new NoticeItem(
                                "preview", currentUserId, extractedText,
                                pendingPreviewUrl, filename, pendingPreviewMime);
                        teacherPreviewBox.addView(buildOriginalFileCard(previewItem));
                        teacherPreviewBox.setVisibility(View.VISIBLE);
                        if (teacherTitleCard != null) teacherTitleCard.setVisibility(View.GONE);
                        if (teacherBodyCard != null) teacherBodyCard.setVisibility(View.GONE);
                    }
                    setSendResult(
                            "📄 미리보기 — " + filename + " · " + charCount + "자\n"
                                    + "↓ 발송 버튼을 눌러 학부모에게 보내세요.",
                            true);
                } catch (Exception error) {
                    setSendResult("응답 파싱 실패\n" + result.body, false);
                }
            });
        });
    }

    /** 텍스트 추출만 — Notice 저장·발송 X (미리보기용). */
    private ApiResult postMultipartExtractText(String filename, byte[] fileBytes) {
        ApiResult result = new ApiResult();
        HttpURLConnection conn = null;
        String boundary = "----DaonBoundary" + System.currentTimeMillis();
        try {
            URL url = new URL(BASE_URL + "/notice/extract-text");
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(30000);
            conn.setReadTimeout(180000);
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Content-Type",
                    "multipart/form-data; boundary=" + boundary);
            if (!currentUserId.isEmpty()) {
                conn.setRequestProperty("X-User-Id", currentUserId);
            }
            conn.setDoOutput(true);

            try (OutputStream os = conn.getOutputStream()) {
                writeMultipartFile(os, boundary, "file", filename, fileBytes);
                os.write(("--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
            }

            int code = conn.getResponseCode();
            InputStream stream = code >= 200 && code < 300
                    ? conn.getInputStream() : conn.getErrorStream();
            result.body = readStream(stream);
            if (code < 200 || code >= 300) {
                result.error = "HTTP " + code + "\n" + result.body;
            }
        } catch (Exception error) {
            result.error = error.getMessage() == null ? error.toString() : error.getMessage();
        } finally {
            if (conn != null) conn.disconnect();
        }
        return result;
    }

    private ApiResult postMultipartUpload(String teacherId, String parentId,
                                          String filename, byte[] fileBytes) {
        ApiResult result = new ApiResult();
        HttpURLConnection conn = null;
        String boundary = "----DaonBoundary" + System.currentTimeMillis();
        try {
            URL url = new URL(BASE_URL + "/notice/upload");
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(30000);
            conn.setReadTimeout(180000);  // LibreOffice 변환은 시간 걸릴 수 있음
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Content-Type",
                    "multipart/form-data; boundary=" + boundary);
            if (!currentUserId.isEmpty()) {
                conn.setRequestProperty("X-User-Id", currentUserId);
            }
            conn.setDoOutput(true);

            try (OutputStream os = conn.getOutputStream()) {
                writeMultipartField(os, boundary, "teacher_id", teacherId);
                writeMultipartField(os, boundary, "parent_id", parentId);
                writeMultipartFile(os, boundary, "file", filename, fileBytes);
                os.write(("--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
            }

            int code = conn.getResponseCode();
            InputStream stream = code >= 200 && code < 300
                    ? conn.getInputStream() : conn.getErrorStream();
            result.body = readStream(stream);
            if (code < 200 || code >= 300) {
                result.error = "HTTP " + code + "\n" + result.body;
            }
        } catch (Exception error) {
            result.error = error.getMessage() == null ? error.toString() : error.getMessage();
        } finally {
            if (conn != null) conn.disconnect();
        }
        return result;
    }

    private void writeMultipartField(OutputStream os, String boundary,
                                     String name, String value) throws IOException {
        os.write(("--" + boundary + "\r\n").getBytes(StandardCharsets.UTF_8));
        os.write(("Content-Disposition: form-data; name=\"" + name + "\"\r\n\r\n")
                .getBytes(StandardCharsets.UTF_8));
        os.write(value.getBytes(StandardCharsets.UTF_8));
        os.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }

    private void writeMultipartFile(OutputStream os, String boundary,
                                    String name, String filename, byte[] data)
            throws IOException {
        os.write(("--" + boundary + "\r\n").getBytes(StandardCharsets.UTF_8));
        os.write(("Content-Disposition: form-data; name=\"" + name + "\"; filename=\""
                + filename + "\"\r\n").getBytes(StandardCharsets.UTF_8));
        os.write("Content-Type: application/octet-stream\r\n\r\n"
                .getBytes(StandardCharsets.UTF_8));
        os.write(data);
        os.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }

    private byte[] readAllBytes(InputStream is) throws IOException {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = is.read(buf)) != -1) baos.write(buf, 0, n);
        return baos.toByteArray();
    }

    private String queryDisplayName(Uri uri) {
        String name = "upload.bin";
        try (Cursor c = getContentResolver().query(uri, null, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                int idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (idx >= 0) {
                    String value = c.getString(idx);
                    if (value != null && !value.isEmpty()) name = value;
                }
            }
        } catch (Exception ignored) {
            // ContentResolver query 실패는 무시하고 기본 파일명 사용
        }
        return name;
    }

    private long querySize(Uri uri) {
        try (Cursor c = getContentResolver().query(uri, null, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                int idx = c.getColumnIndex(OpenableColumns.SIZE);
                if (idx >= 0 && !c.isNull(idx)) return c.getLong(idx);
            }
        } catch (Exception ignored) {
            // 일부 ContentProvider는 SIZE 컬럼을 노출 안 함 — 라벨에서 빠져도 OK
        }
        return 0;
    }

    private String sampleNotice() {
        return "내일 현장학습이 있습니다.\n아이는 물병과 도시락을 가져와 주세요.\n아침 9시까지 학교 운동장으로 와 주세요.";
    }

    // ============================================================
    //  TTS
    // ============================================================
    private void playTts() {
        playTtsUrl(currentTtsUrl, playButton,
                ttsLabel(), true);
    }

    private LinearLayout buildSpeedControl() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);
        row.setPadding(dp(16), dp(4), dp(16), dp(4));

        String[] labels = {uiText("slow"), uiText("normal"), uiText("fast")};
        float[] speeds = {0.5f, 0.75f, 1.0f};
        speedButtons = new Button[3];

        for (int i = 0; i < 3; i++) {
            final int idx = i;
            Button b = new Button(this);
            b.setText(labels[i]);
            b.setTextSize(13);
            b.setAllCaps(false);
            b.setPadding(dp(20), dp(6), dp(20), dp(6));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
            lp.setMargins(dp(4), 0, dp(4), 0);
            b.setLayoutParams(lp);
            final float speed = speeds[i];
            b.setOnClickListener(v -> {
                ttsSpeed = speed;
                updateSpeedButtonStyles();
                if (player != null) {
                    try {
                        android.media.PlaybackParams pp = new android.media.PlaybackParams();
                        pp.setSpeed(ttsSpeed);
                        player.setPlaybackParams(pp);
                    } catch (IllegalStateException ignored) { }
                }
            });
            speedButtons[i] = b;
            row.addView(b);
        }
        updateSpeedButtonStyles();
        return row;
    }

    private void updateSpeedButtonStyles() {
        if (speedButtons == null) return;
        float[] speeds = {0.5f, 0.75f, 1.0f};
        for (int i = 0; i < speedButtons.length; i++) {
            boolean selected = Math.abs(ttsSpeed - speeds[i]) < 0.01f;
            GradientDrawable bg = new GradientDrawable();
            bg.setCornerRadius(dp(20));
            bg.setColor(selected ? COLOR_PEACH_DEEP : Color.parseColor("#E8E8E8"));
            speedButtons[i].setBackground(bg);
            speedButtons[i].setTextColor(selected ? Color.WHITE : COLOR_INK);
            speedButtons[i].setTypeface(null, selected ? Typeface.BOLD : Typeface.NORMAL);
        }
    }

    private View findTaggedSibling(View anchor, String tag) {
        if (!(anchor.getParent() instanceof ViewGroup)) return null;
        ViewGroup parent = (ViewGroup) anchor.getParent();
        for (int i = 0; i < parent.getChildCount(); i++) {
            View child = parent.getChildAt(i);
            if (tag.equals(child.getTag())) return child;
        }
        return null;
    }

    // ============================================================
    //  STT 음성 질문
    // ============================================================
    private LinearLayout buildSttSection() {
        LinearLayout section = new LinearLayout(this);
        section.setOrientation(LinearLayout.VERTICAL);
        section.setPadding(dp(16), dp(8), dp(16), dp(8));

        // 팁 카드
        LinearLayout tipCard = new LinearLayout(this);
        tipCard.setOrientation(LinearLayout.VERTICAL);
        tipCard.setPadding(dp(16), dp(12), dp(16), dp(12));
        GradientDrawable tipBg = new GradientDrawable();
        tipBg.setCornerRadius(dp(12));
        tipBg.setColor(Color.parseColor("#FFF3E6"));
        tipBg.setStroke(dp(1), COLOR_LINE);
        tipCard.setBackground(tipBg);

        TextView tipTitle = new TextView(this);
        tipTitle.setText("💬  " + sttTipHeading());
        tipTitle.setTextSize(12);
        tipTitle.setTextColor(COLOR_PEACH_INK);
        tipTitle.setTypeface(null, Typeface.BOLD);
        tipTitle.setPadding(0, 0, 0, dp(6));
        tipCard.addView(tipTitle);

        Map<String, String[]> tips = STT_TIPS.get(selectedLanguage);
        if (tips == null) tips = STT_TIPS.get("ko_easy");
        for (Map.Entry<String, String[]> entry : tips.entrySet()) {
            TextView tv = new TextView(this);
            tv.setText("• " + entry.getValue()[0]);
            tv.setTextSize(13);
            tv.setTextColor(COLOR_INK2);
            tv.setPadding(dp(4), dp(2), 0, dp(2));
            tipCard.addView(tv);
        }
        section.addView(tipCard);

        // 마이크 버튼
        sttButton = new Button(this);
        sttButton.setText("🎤  " + uiText("speak_to_ask"));
        sttButton.setTextSize(15);
        sttButton.setTextColor(Color.WHITE);
        sttButton.setAllCaps(false);
        sttButton.setTypeface(null, Typeface.BOLD);
        sttButton.setPadding(dp(20), dp(14), dp(20), dp(14));
        LinearLayout.LayoutParams btnLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        btnLp.topMargin = dp(10);
        sttButton.setLayoutParams(btnLp);
        GradientDrawable sttBg = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                new int[]{Color.parseColor("#7B61FF"), Color.parseColor("#5A45D4")});
        sttBg.setCornerRadius(dp(14));
        sttButton.setBackground(sttBg);
        sttButton.setOnClickListener(v -> startStt());
        section.addView(sttButton);

        return section;
    }

    private void startStt() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 200);
            return;
        }
        if (speechRecognizer != null) speechRecognizer.destroy();
        speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this);
        speechRecognizer.setRecognitionListener(new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle p) {
                runOnUiThread(() -> sttButton.setText("🎤  듣고 있어요..."));
            }
            @Override public void onResults(Bundle results) {
                ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                runOnUiThread(() -> {
                    sttButton.setText("🎤  " + uiText("speak_to_ask"));
                    if (matches != null && !matches.isEmpty()) handleSttResult(matches.get(0));
                });
            }
            @Override public void onError(int error) {
                runOnUiThread(() -> {
                    sttButton.setText("🎤  " + uiText("speak_to_ask"));
                    Toast.makeText(MainActivity.this, "인식 실패, 다시 시도해주세요", Toast.LENGTH_SHORT).show();
                });
            }
            @Override public void onBeginningOfSpeech() {}
            @Override public void onRmsChanged(float v) {}
            @Override public void onBufferReceived(byte[] b) {}
            @Override public void onEndOfSpeech() {}
            @Override public void onPartialResults(Bundle b) {}
            @Override public void onEvent(int t, Bundle b) {}
        });

        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, sttLocale());
        intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3);
        speechRecognizer.startListening(intent);
    }

    private String sttLocale() {
        switch (selectedLanguage) {
            case "vi":  return "vi-VN";
            case "en":  return "en-US";
            case "ru":  return "ru-RU";
            case "ms":  return "ms-MY";
            case "mn":  return "mn-MN";
            case "zh":  return "zh-CN";
            case "th":  return "th-TH";
            case "ja":  return "ja-JP";
            default:    return "ko-KR"; // vi_demo 포함
        }
    }

    private String sttTipHeading() {
        switch (selectedLanguage) {
            case "vi":  return "Hãy nói như thế này";
            case "en":  return "Try saying this";
            case "ru":  return "Попробуйте сказать";
            case "ms":  return "Cuba sebut begini";
            case "mn":  return "Ингэж хэлж үзээрэй";
            case "zh":  return "请这样说";
            case "th":  return "ลองพูดแบบนี้";
            case "ja":  return "こう話してみてください";
            default:    return "이렇게 말해보세요"; // ko_easy, vi_demo
        }
    }

    private void handleSttResult(String recognized) {
        String category = matchCategory(recognized);
        if (category == null) {
            Toast.makeText(this, "\"" + recognized + "\"\n인식했지만 해당 항목을 찾지 못했어요", Toast.LENGTH_LONG).show();
            return;
        }
        String spoken = buildSpokenText(category);
        if (spoken.isEmpty()) {
            Toast.makeText(this, category + " 항목이 없습니다", Toast.LENGTH_SHORT).show();
            return;
        }
        speakText(spoken);
    }

    private String matchCategory(String recognized) {
        String lower = recognized.toLowerCase();
        Map<String, String[]> tips = STT_TIPS.get(selectedLanguage);
        if (tips == null) tips = STT_TIPS.get("ko_easy");
        for (Map.Entry<String, String[]> entry : tips.entrySet()) {
            String[] phrases = entry.getValue();
            for (int i = 1; i < phrases.length; i++) {
                if (lower.contains(phrases[i].toLowerCase())) return entry.getKey();
            }
        }
        return null;
    }

    private String buildSpokenText(String category) {
        boolean useKo = "vi_demo".equals(selectedLanguage);
        if ("주제".equals(category)) {
            if (!useKo && !currentNoticeTitleTranslated.isEmpty()) return currentNoticeTitleTranslated;
            return currentNoticeTitle.isEmpty() ? "" : currentNoticeTitle;
        }
        StringBuilder sb = new StringBuilder();
        if (currentCards != null) {
            for (int i = 0; i < currentCards.length(); i++) {
                JSONObject card = currentCards.optJSONObject(i);
                if (card == null) continue;
                String chip = safeString(card, "chip");
                if (!chip.contains(category)) continue;
                String val = useKo
                        ? safeString(card, "value_ko")
                        : firstNonBlank(safeString(card, "value_translated"), safeString(card, "value_ko"));
                if (!val.isEmpty()) sb.append(val).append(". ");
            }
        }
        if (sb.length() == 0 && currentAnalysisItems != null) {
            for (int i = 0; i < currentAnalysisItems.length(); i++) {
                JSONObject item = currentAnalysisItems.optJSONObject(i);
                if (item == null) continue;
                String cat = safeString(item, "category");
                if (!cat.contains(category)) continue;
                String title = useKo
                        ? safeString(item, "title_ko")
                        : firstNonBlank(safeString(item, "title_translated"), safeString(item, "title_ko"));
                if (!title.isEmpty()) sb.append(title).append(". ");
            }
        }
        return sb.toString().trim();
    }

    private void speakText(String text) {
        if (!ttsEngineReady || ttsEngine == null) {
            Toast.makeText(this, text, Toast.LENGTH_LONG).show();
            return;
        }
        Locale locale;
        switch (selectedLanguage) {
            case "vi":      locale = new Locale("vi", "VN"); break;
            case "vi_demo": locale = Locale.KOREAN; break;
            case "en":  locale = Locale.US; break;
            case "ru":  locale = new Locale("ru", "RU"); break;
            case "ms":  locale = new Locale("ms", "MY"); break;
            case "mn":  locale = new Locale("mn", "MN"); break;
            case "zh":  locale = Locale.CHINA; break;
            case "th":  locale = new Locale("th", "TH"); break;
            case "ja":  locale = Locale.JAPAN; break;
            default:    locale = Locale.KOREAN; break;
        }
        int result = ttsEngine.setLanguage(locale);
        if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
            ttsEngine.setLanguage(Locale.KOREAN);
        }
        ttsEngine.setSpeechRate(ttsSpeed);
        ttsEngine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "stt_response");
    }

    private void playTtsUrl(String ttsUrl, Button activeButton, String idleLabel, boolean allowFallback) {
        if (player != null) {
            try {
                if (player.isPlaying()) {
                    player.stop();
                    releasePlayer();
                    resetTtsButtons();
                    return;
                }
            } catch (IllegalStateException ignored) { }
        }
        releasePlayer();
        try {
            if (!TextUtils.isEmpty(ttsUrl)) {
                String url = ttsUrl.startsWith("http") ? ttsUrl : BASE_URL + ttsUrl;
                player = new MediaPlayer();
                player.setDataSource(url);
                player.setOnPreparedListener(mp -> {
                    if (ttsSpeed != 1.0f) {
                        try {
                            android.media.PlaybackParams pp = new android.media.PlaybackParams();
                            pp.setSpeed(ttsSpeed);
                            mp.setPlaybackParams(pp);
                        } catch (IllegalStateException ignored) { }
                    }
                    mp.start();
                    if (activeButton != null) activeButton.setText("⏸  정지");
                });
                player.setOnCompletionListener(mp -> {
                    releasePlayer();
                    resetTtsButtons();
                });
                player.prepareAsync();
            } else if (allowFallback) {
                player = MediaPlayer.create(this, R.raw.tts_output);
                if (ttsSpeed != 1.0f) {
                    try {
                        android.media.PlaybackParams pp = new android.media.PlaybackParams();
                        pp.setSpeed(ttsSpeed);
                        player.setPlaybackParams(pp);
                    } catch (IllegalStateException ignored) { }
                }
                player.start();
                if (activeButton != null) activeButton.setText("⏸  정지");
                player.setOnCompletionListener(mp -> {
                    releasePlayer();
                    resetTtsButtons();
                });
            }
        } catch (Exception error) {
            if (analysisStatusText != null) {
                analysisStatusText.setVisibility(View.VISIBLE);
                ((View) analysisStatusText.getParent()).setVisibility(View.VISIBLE);
                analysisStatusText.setText("TTS 재생 실패: " + error.getMessage());
            }
        }
    }

    private void resetTtsButtons() {
        if (playButton != null)
            playButton.setText(ttsLabel());
        if (easyKoPlayButton != null)
            easyKoPlayButton.setText(easyKoTtsLabel());
    }

    // ============================================================
    //  LANG PILL  (top-right)
    // ============================================================
    private Button makeLangPillButton() {
        Button b = new Button(this);
        b.setText(langPillText());
        b.setTextSize(12);
        b.setAllCaps(false);
        b.setTextColor(COLOR_INK);
        b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        b.setPadding(dp(12), dp(7), dp(12), dp(7));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.argb(220, 255, 255, 255));
        bg.setCornerRadius(dp(999));
        bg.setStroke(dp(1), COLOR_LINE);
        b.setBackground(bg);
        b.setStateListAnimator(null);
        b.setMinHeight(dp(34));
        b.setMinimumHeight(dp(34));
        b.setOnClickListener(v -> showLanguageDialog());
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        b.setLayoutParams(p);
        return b;
    }

    private void showLanguageDialog() {
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle("Language / 언어 선택");
        builder.setItems(LANG_LABELS, (dialog, which) -> {
            if (LANG_CODES[which].equals(selectedLanguage)) return;
            selectedLanguage = LANG_CODES[which];
            saveLanguage(selectedLanguage);
            if (langPillBtn != null) {
                langPillBtn.setText(langPillText());
            }
            releasePlayer();
            currentTtsUrl = "";
            currentEasyKoTtsUrl = "";
            // AI 화면이면 자동 재분석
            if (selectedNotice != null && analysisStatusText != null) {
                showAIOverlay(selectedNotice);
            } else if (inboxListBox != null) {
                // 학부모 홈 — 인사말 갱신을 위해 화면 재구성
                showParentHome();
            }
        });
        builder.show();
    }

    /** 학부모 홈 헤더 인사말 — selectedLanguage에 맞춰 모국어로 표시. */
    private String greetingForLanguage() {
        switch (selectedLanguage) {
            case "vi": return "Xin chào,";
            case "en": return "Hello,";
            case "ru": return "Здравствуйте,";
            case "ms": return "Selamat datang,";
            case "mn": return "Сайн байна уу,";
            case "zh": return "您好,";
            case "th": return "สวัสดี,";
            case "ja": return "こんにちは,";
            case "ko_easy": return "안녕하세요,";
            default: return "Xin chào,";
        }
    }

    private void showInitialLanguageDialogIfNeeded() {
        if (getSharedPreferences(PREFS_NAME, MODE_PRIVATE).contains(PREF_KEY_LANG)) return;
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle("Language / 언어 선택");
        builder.setItems(LANG_LABELS, (dialog, which) -> {
            selectedLanguage = LANG_CODES[which];
            saveLanguage(selectedLanguage);
            if (langPillBtn != null) {
                langPillBtn.setText(langPillText());
            }
        });
        builder.show();
    }

    // ============================================================
    //  TEXT SIZE CONTROL (글자 크기 조절)
    // ============================================================
    private LinearLayout textSizeControls() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        row.setLayoutParams(spacedParams());

        TextView label = text("글자 크기", 11, COLOR_INK3, true);
        label.setAllCaps(true);
        label.setLetterSpacing(0.06f);
        label.setPadding(0, 0, dp(10), 0);
        row.addView(label);

        Button minus = textSizeBtn("A−", v -> adjustTextSize(-2f));
        Button plus  = textSizeBtn("A+", v -> adjustTextSize(+2f));
        row.addView(minus);
        TextView gap = new TextView(this); gap.setWidth(dp(6));
        row.addView(gap);
        row.addView(plus);
        return row;
    }

    private Button textSizeBtn(String label, View.OnClickListener listener) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(13);
        b.setTextColor(COLOR_INK);
        b.setAllCaps(false);
        b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        b.setPadding(dp(12), dp(2), dp(12), dp(2));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(999));
        bg.setStroke(dp(1), COLOR_LINE);
        b.setBackground(bg);
        b.setStateListAnimator(null);
        b.setMinHeight(dp(32));
        b.setMinimumHeight(dp(32));
        b.setOnClickListener(listener);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, dp(32));
        b.setLayoutParams(p);
        return b;
    }

    private void adjustTextSize(float delta) {
        currentTextSize = Math.max(TEXT_SIZE_MIN, Math.min(TEXT_SIZE_MAX, currentTextSize + delta));
        if (checklistText != null)   checklistText.setTextSize(currentTextSize);
        if (easyKoText != null)      easyKoText.setTextSize(currentTextSize);
        if (translationText != null) translationText.setTextSize(currentTextSize);
    }

    // ============================================================
    //  BUILD SCREEN  (공통: 그라데이션 bg + greet/title 헤더 + 콘텐츠 + 옵션 탭바)
    // ============================================================
    private void buildScreen(String greet, String bigTitle, String subtitle,
                             boolean withLangPill, int activeTabIndex, boolean isParent) {
        releasePlayer();
        FrameLayout outer = new FrameLayout(this);
        outer.setBackground(daonGradient());

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setLayoutParams(new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int bottomPad = activeTabIndex >= 0 ? dp(96) : dp(28);
        root.setPadding(0, 0, 0, bottomPad);
        scroll.addView(root);

        // 헤더 (greet + title-xl + subtitle)
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        int headerTopPad = withLangPill ? dp(70) : dp(38);
        header.setPadding(dp(20), headerTopPad, dp(20), dp(8));

        if (greet != null && !greet.isEmpty()) {
            TextView g = text(greet, 13, COLOR_INK3, false);
            header.addView(g);
        }
        TextView t = text(bigTitle, 26, COLOR_INK, true);
        t.setLetterSpacing(-0.02f);
        t.setLineSpacing(0, 1.12f);
        if (greet == null || greet.isEmpty()) {
            // login mode — show subtitle as small label below title
            header.addView(t);
            if (subtitle != null && !subtitle.isEmpty()) {
                TextView s = text(subtitle, 13, COLOR_INK2, false);
                s.setPadding(0, dp(4), 0, 0);
                header.addView(s);
            }
        } else {
            header.addView(t);
            if (subtitle != null && !subtitle.isEmpty()) {
                TextView s = text(subtitle, 13, COLOR_INK3, false);
                s.setPadding(0, dp(4), 0, 0);
                header.addView(s);
            }
        }
        root.addView(header);

        // 콘텐츠
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(18), dp(8), dp(18), 0);
        root.addView(content);

        outer.addView(scroll);

        // 우상단 lang pill (floating)
        if (withLangPill) {
            langPillBtn = makeLangPillButton();
            FrameLayout.LayoutParams lpp = new FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.WRAP_CONTENT,
                    FrameLayout.LayoutParams.WRAP_CONTENT);
            lpp.gravity = Gravity.TOP | Gravity.END;
            lpp.setMargins(0, dp(38), dp(16), 0);
            outer.addView(langPillBtn, lpp);
        }

        // 하단 탭바
        if (activeTabIndex >= 0) {
            outer.addView(makeBottomTabBar(activeTabIndex, isParent));
        }
        setContentView(outer);
    }

    private GradientDrawable daonGradient() {
        return new GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                new int[]{Color.parseColor("#FFE8D4"),
                          Color.parseColor("#D8F0E4"),
                          Color.parseColor("#FFF5CC")});
    }

    private LinearLayout makeBottomTabBar(int activeIndex, boolean isParent) {
        String[] icons  = isParent
                ? new String[]{"🏠", "📷", "📅", "💬", "👤"}
                : new String[]{"🏠", "✏️", "📊", "💬", "👤"};
        String[] labels = isParent
                ? new String[]{"홈", "번역", "일정", "회신", "나"}
                : new String[]{"우리반", "작성", "현황", "답장", "나"};
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(8), dp(8), dp(8), dp(14));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.argb(235, 255, 250, 243));
        bg.setStroke(dp(1), Color.argb(20, 0, 0, 0));
        bar.setBackground(bg);

        for (int i = 0; i < icons.length; i++) {
            bar.addView(makeTabItem(icons[i], labels[i], i == activeIndex));
        }

        FrameLayout.LayoutParams p = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, dp(72));
        p.gravity = Gravity.BOTTOM;
        bar.setLayoutParams(p);
        return bar;
    }

    private LinearLayout makeTabItem(String icon, String label, boolean active) {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER);
        col.setPadding(dp(2), dp(4), dp(2), dp(2));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.MATCH_PARENT, 1);
        col.setLayoutParams(p);

        TextView ic = new TextView(this);
        ic.setText(icon);
        ic.setTextSize(18);
        ic.setGravity(Gravity.CENTER);
        if (active) {
            GradientDrawable bg = new GradientDrawable();
            bg.setColor(COLOR_PEACH);
            bg.setCornerRadius(dp(10));
            ic.setBackground(bg);
            int s = dp(32);
            LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(s, s);
            ic.setLayoutParams(ip);
            ic.setPadding(0, 0, 0, dp(2));
        }
        col.addView(ic);

        TextView lab = text(label, 10, active ? COLOR_PEACH_INK : COLOR_INK3, active);
        lab.setGravity(Gravity.CENTER);
        lab.setPadding(0, dp(2), 0, 0);
        col.addView(lab);

        // 비활성 탭만 클릭 시 안내 토스트. 활성 탭은 현재 화면이라 동작 X.
        if (!active) {
            col.setClickable(true);
            col.setFocusable(true);
            col.setOnClickListener(v -> notImplementedToast(label));
        }
        return col;
    }

    // ============================================================
    //  COMMON UI HELPERS
    // ============================================================
    private TextView sectionLabel(String text) {
        TextView label = text(text, 11, COLOR_INK3, true);
        label.setAllCaps(true);
        label.setLetterSpacing(0.06f);
        label.setPadding(dp(4), dp(16), 0, dp(8));
        return label;
    }

    private EditText input(String hint, String value) {
        EditText edit = new EditText(this);
        edit.setHint(hint);
        edit.setText(value);
        edit.setSingleLine(true);
        edit.setTextSize(15);
        edit.setTextColor(COLOR_INK);
        edit.setHintTextColor(COLOR_INK4);
        edit.setPadding(dp(16), dp(12), dp(16), dp(12));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(COLOR_PAPER2);
        bg.setCornerRadius(dp(14));
        bg.setStroke(dp(1), COLOR_LINE);
        edit.setBackground(bg);
        edit.setLayoutParams(spacedParams());
        return edit;
    }

    private EditText multiInput(String hint, String value) {
        EditText edit = input(hint, value);
        edit.setSingleLine(false);
        edit.setMinLines(5);
        edit.setGravity(Gravity.TOP | Gravity.START);
        return edit;
    }

    private GradientDrawable transparentBg() {
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.TRANSPARENT);
        return bg;
    }

    private GradientDrawable roundedFill(int color, int radius) {
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(color);
        bg.setCornerRadius(radius);
        return bg;
    }

    private Button bigPrimaryButton(String label, View.OnClickListener listener) {
        Button b = primaryButton(label, listener);
        b.setTextSize(16);
        b.setPadding(dp(20), dp(18), dp(20), dp(18));
        b.setMinHeight(dp(56));
        b.setMinimumHeight(dp(56));
        return b;
    }

    private Button primaryButton(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(15);
        button.setTextColor(Color.WHITE);
        button.setAllCaps(false);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setPadding(dp(14), dp(14), dp(14), dp(14));
        GradientDrawable bg = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                new int[]{COLOR_PEACH_DEEP, Color.parseColor("#E07744")});
        bg.setCornerRadius(dp(14));
        button.setBackground(bg);
        button.setStateListAnimator(null);
        button.setElevation(dp(3));
        button.setOnClickListener(listener);
        button.setLayoutParams(spacedParams());
        return button;
    }

    private Button bottomLinkButton(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(15);
        button.setTextColor(Color.WHITE);
        button.setAllCaps(false);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setPadding(dp(14), dp(10), dp(14), dp(10));
        GradientDrawable bg = new GradientDrawable(
                GradientDrawable.Orientation.LEFT_RIGHT,
                new int[]{COLOR_PEACH_DEEP, Color.parseColor("#E07744")});
        bg.setCornerRadius(dp(18));
        button.setBackground(bg);
        button.setStateListAnimator(null);
        button.setElevation(dp(8));
        button.setOnClickListener(listener);
        return button;
    }

    private Button smallTextButton(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(12);
        button.setAllCaps(false);
        button.setTextColor(COLOR_INK3);
        button.setTypeface(Typeface.DEFAULT, Typeface.NORMAL);
        button.setPadding(dp(8), dp(6), dp(8), dp(6));
        button.setBackground(null);
        button.setStateListAnimator(null);
        button.setOnClickListener(listener);
        LinearLayout.LayoutParams lp = spacedParams();
        lp.topMargin = dp(4);
        lp.bottomMargin = dp(8);
        button.setLayoutParams(lp);
        return button;
    }

    private Button outlineButton(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(14);
        button.setAllCaps(false);
        button.setTextColor(COLOR_INK2);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setPadding(dp(14), dp(13), dp(14), dp(13));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(14));
        bg.setStroke(dp(1), COLOR_LINE);
        button.setBackground(bg);
        button.setStateListAnimator(null);
        button.setOnClickListener(listener);
        button.setLayoutParams(spacedParams());
        return button;
    }

    private LinearLayout cardWithView(String heading, View bodyView, int bgColor) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(16), dp(16), dp(16), dp(16));
        box.setLayoutParams(spacedParams());
        GradientDrawable drawable = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR, cardGradient(bgColor));
        drawable.setCornerRadius(dp(18));
        if (bgColor == Color.WHITE || bgColor == COLOR_PAPER) {
            drawable.setStroke(dp(1), COLOR_LINE);
        }
        box.setBackground(drawable);
        box.setElevation(dp(1));
        if (heading != null && !heading.isEmpty()) {
            TextView h = text(heading, 11, cardLabelColor(bgColor), true);
            h.setAllCaps(true);
            h.setLetterSpacing(0.06f);
            h.setPadding(0, 0, 0, dp(10));
            box.addView(h);
        }
        // body color match
        if (bodyView instanceof TextView) {
            int ink = bodyTextColor(bgColor);
            ((TextView) bodyView).setTextColor(ink);
        }
        box.addView(bodyView);
        return box;
    }

    private int[] cardGradient(int bgColor) {
        if (bgColor == COLOR_PEACH)    return new int[]{COLOR_PEACH, blend(COLOR_PEACH, COLOR_PEACH_DEEP, 0.25f)};
        if (bgColor == COLOR_MINT)     return new int[]{COLOR_MINT, blend(COLOR_MINT, COLOR_MINT_DEEP, 0.25f)};
        if (bgColor == COLOR_LEMON)    return new int[]{COLOR_LEMON, Color.parseColor("#FFE07A")};
        if (bgColor == COLOR_LAVENDER) return new int[]{COLOR_LAVENDER, Color.parseColor("#D1C5F2")};
        if (bgColor == COLOR_SKY)      return new int[]{COLOR_SKY, Color.parseColor("#B8DDFF")};
        return new int[]{bgColor, bgColor};
    }

    private int cardLabelColor(int bgColor) {
        if (bgColor == COLOR_PEACH)    return COLOR_PEACH_INK;
        if (bgColor == COLOR_MINT)     return COLOR_MINT_INK;
        if (bgColor == COLOR_LEMON)    return COLOR_LEMON_INK;
        if (bgColor == COLOR_LAVENDER) return COLOR_LAVENDER_INK;
        return COLOR_INK3;
    }

    private int bodyTextColor(int bgColor) {
        if (bgColor == COLOR_PEACH)    return COLOR_PEACH_INK;
        if (bgColor == COLOR_MINT)     return COLOR_MINT_INK;
        if (bgColor == COLOR_LEMON)    return COLOR_LEMON_INK;
        if (bgColor == COLOR_LAVENDER) return COLOR_LAVENDER_INK;
        return COLOR_INK;
    }

    private static int blend(int a, int b, float ratio) {
        int ar = (a >> 16) & 0xff, ag = (a >> 8) & 0xff, ab = a & 0xff;
        int br = (b >> 16) & 0xff, bg = (b >> 8) & 0xff, bb = b & 0xff;
        int r = (int) (ar * (1 - ratio) + br * ratio);
        int g = (int) (ag * (1 - ratio) + bg * ratio);
        int bl = (int) (ab * (1 - ratio) + bb * ratio);
        return Color.rgb(r, g, bl);
    }

    private LinearLayout.LayoutParams spacedParams() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, 0, 0, dp(10));
        return params;
    }

    private TextView text(String value, int sp, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value == null ? "" : value);
        view.setTextSize(sp);
        view.setTextColor(color);
        view.setLineSpacing(0, 1.25f);
        view.setIncludeFontPadding(true);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    // ============================================================
    //  NETWORK
    // ============================================================
    private void getJson(String path, ApiCallback callback) {
        request("GET", path, null, callback);
    }

    private void postJson(String path, JSONObject payload, ApiCallback callback) {
        request("POST", path, payload, callback);
    }

    private void request(String method, String path, JSONObject payload, ApiCallback callback) {
        executor.execute(() -> {
            ApiResult result = new ApiResult();
            HttpURLConnection conn = null;
            try {
                URL url = new URL(BASE_URL + path);
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod(method);
                conn.setConnectTimeout(30000);
                conn.setReadTimeout(600000);  // analyze — NLLB 첫 다운로드 대비 10분 (이후 캐시되어 빠름)
                conn.setRequestProperty("Accept", "application/json");
                if (!currentUserId.isEmpty()) {
                    conn.setRequestProperty("X-User-Id", currentUserId);
                }
                if (payload != null) {
                    conn.setDoOutput(true);
                    conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                    try (OutputStream os = conn.getOutputStream()) {
                        os.write(payload.toString().getBytes(StandardCharsets.UTF_8));
                    }
                }
                int code = conn.getResponseCode();
                InputStream stream = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
                result.body = readStream(stream);
                if (code < 200 || code >= 300) result.error = "HTTP " + code + "\n" + result.body;
            } catch (Exception error) {
                result.error = error.getMessage() == null ? error.toString() : error.getMessage();
            } finally {
                if (conn != null) conn.disconnect();
            }
            runOnUiThread(() -> callback.done(result));
        });
    }

    private String readStream(InputStream stream) throws Exception {
        if (stream == null) return "";
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) builder.append(line).append('\n');
        }
        return builder.toString().trim();
    }

    // ============================================================
    //  HELPERS
    // ============================================================
    private String getTranslationForLanguage(JSONObject data, String code) {
        switch (code) {
            case "en": return optStringDeep(data, "en_text", "english", "translation_en");
            case "ru": return optStringDeep(data, "ru_text", "russian", "translation_ru");
            case "ms": return optStringDeep(data, "ms_text", "malay", "translation_ms");
            case "mn": return optStringDeep(data, "mn_text", "mongolian", "translation_mn");
            case "vi_demo":
            case "vi": return optStringDeep(data, "corrected_vi_text", "corrected_translation",
                    "vi_corrected_translation", "final_vi_text", "vi_text", "vietnamese", "translation_vi");
            case "zh": return optStringDeep(data, "zh_text", "chinese", "translation_zh");
            case "th": return optStringDeep(data, "th_text", "thai", "translation_th");
            case "ja": return optStringDeep(data, "ja_text", "japanese", "translation_ja");
            default: return "";
        }
    }

    private String languageDisplayName(String code) {
        if ("ko_easy".equals(code)) return uiText("easy_korean");
        for (int i = 0; i < LANG_CODES.length; i++) {
            if (LANG_CODES[i].equals(code)) return LANG_NAMES[i];
        }
        return code;
    }

    private String backendLanguageCode(String code) {
        return "vi_demo".equals(code) ? "vi" : code;
    }

    private String ttsLabel() {
        return "🔊  " + selectedLanguageNative() + " " + uiText("listen");
    }

    private String easyKoTtsLabel() {
        return "🔊  " + uiText("listen_easy_korean");
    }

    private String langPillText() {
        return "🌐  " + selectedLanguageNative() + "  ▾";
    }

    private String selectedLanguageNative() {
        if ("ko_easy".equals(selectedLanguage)) return "쉬운 한국어";
        return LANG_NATIVE[langIndex(selectedLanguage)];
    }

    private String selectedLanguageFlag() {
        if ("ko_easy".equals(selectedLanguage)) return "KR";
        return LANG_FLAGS[langIndex(selectedLanguage)];
    }

    private String uiText(String key) {
        String lang = isSupportedLanguage(selectedLanguage) ? selectedLanguage : "vi";
        if ("vi_demo".equals(lang)) lang = "ko";
        switch (lang) {
            case "en":
                switch (key) {
                    case "ai_translate": return "AI Translate";
                    case "translation": return "Translation";
                    case "ai_subtitle": return "Native language · Easy Korean · Audio";
                    case "analyzing": return "AI is analyzing...";
                    case "analyzing_detail": return "AI is analyzing...\n(Easy Korean → Native language → Audio)";
                    case "timeout": return "Analysis timed out.\nLong notices can take more time.\n\nPlease try again.";
                    case "server_error": return "Server connection failed";
                    case "todo": return "To do";
                    case "easy_korean": return "Easy Korean";
                    case "school_terms": return "School terms";
                    case "listen": return "Listen";
                    case "listen_easy_korean": return "Listen to Easy Korean";
                    case "slow": return "Word by word";
                    case "normal": return "Slowly";
                    case "fast": return "Original";
                    case "speak_to_ask": return "Ask by voice";
                    case "back_to_notice": return "Back to notice";
                    case "refresh_inbox": return "Refresh inbox";
                    case "logout": return "Log out";
                    case "loading_inbox": return "Loading inbox...";
                    case "empty_inbox": return "No notices yet.";
                    case "received_notices": return "Received notices";
                    case "new_notice": return "New notices";
                }
                break;
            case "vi":
                switch (key) {
                    case "ai_translate": return "Dịch bằng AI";
                    case "translation": return "Bản dịch";
                    case "ai_subtitle": return "Tiếng mẹ đẻ · Tiếng Hàn dễ hiểu · Âm thanh";
                    case "analyzing": return "AI đang phân tích...";
                    case "analyzing_detail": return "AI đang phân tích...\n(Tiếng Hàn dễ hiểu → Tiếng mẹ đẻ → Âm thanh)";
                    case "timeout": return "Quá thời gian phân tích.\nThông báo dài có thể cần nhiều thời gian hơn.\n\nVui lòng thử lại.";
                    case "server_error": return "Không thể kết nối máy chủ";
                    case "todo": return "Việc cần làm";
                    case "easy_korean": return "Tiếng Hàn dễ hiểu";
                    case "school_terms": return "Từ ngữ trường học";
                    case "listen": return "Nghe";
                    case "listen_easy_korean": return "Nghe tiếng Hàn dễ hiểu";
                    case "slow": return "Từng từ";
                    case "normal": return "Chậm";
                    case "fast": return "Gốc";
                    case "speak_to_ask": return "Hỏi bằng giọng nói";
                    case "back_to_notice": return "Quay lại thông báo";
                    case "refresh_inbox": return "Tải lại hộp thư";
                    case "logout": return "Đăng xuất";
                    case "loading_inbox": return "Đang tải hộp thư...";
                    case "empty_inbox": return "Chưa có thông báo.";
                    case "received_notices": return "Thông báo đã nhận";
                    case "new_notice": return "Thông báo mới";
                }
                break;
            case "ja":
                switch (key) {
                    case "ai_translate": return "AI翻訳";
                    case "translation": return "翻訳";
                    case "ai_subtitle": return "母語 · やさしい韓国語 · 音声";
                    case "analyzing": return "AIが分析中です...";
                    case "analyzing_detail": return "AIが分析中です...\n(やさしい韓国語 → 母語 → 音声)";
                    case "timeout": return "分析がタイムアウトしました。\n長いお知らせは時間がかかる場合があります。\n\nもう一度お試しください。";
                    case "server_error": return "サーバー接続に失敗しました";
                    case "todo": return "やること";
                    case "easy_korean": return "やさしい韓国語";
                    case "school_terms": return "学校用語";
                    case "listen": return "聞く";
                    case "listen_easy_korean": return "やさしい韓国語を聞く";
                    case "slow": return "一語ずつ";
                    case "normal": return "ゆっくり";
                    case "fast": return "通常";
                    case "speak_to_ask": return "音声で質問";
                    case "back_to_notice": return "お知らせに戻る";
                    case "refresh_inbox": return "受信箱を更新";
                    case "logout": return "ログアウト";
                    case "loading_inbox": return "受信箱を読み込み中...";
                    case "empty_inbox": return "お知らせはありません。";
                    case "received_notices": return "受信したお知らせ";
                    case "new_notice": return "新しいお知らせ";
                }
                break;
            case "zh":
                switch (key) {
                    case "ai_translate": return "AI翻译";
                    case "translation": return "翻译";
                    case "ai_subtitle": return "母语 · 简易韩语 · 语音";
                    case "analyzing": return "AI正在分析...";
                    case "analyzing_detail": return "AI正在分析...\n(简易韩语 → 母语 → 语音)";
                    case "timeout": return "分析超时。\n较长通知可能需要更多时间。\n\n请稍后重试。";
                    case "server_error": return "服务器连接失败";
                    case "todo": return "待办事项";
                    case "easy_korean": return "简易韩语";
                    case "school_terms": return "学校用语";
                    case "listen": return "收听";
                    case "listen_easy_korean": return "收听简易韩语";
                    case "slow": return "逐词";
                    case "normal": return "慢速";
                    case "fast": return "原速";
                    case "speak_to_ask": return "语音提问";
                    case "back_to_notice": return "返回通知";
                    case "refresh_inbox": return "刷新收件箱";
                    case "logout": return "退出登录";
                    case "loading_inbox": return "正在加载收件箱...";
                    case "empty_inbox": return "暂无通知。";
                    case "received_notices": return "收到的通知";
                    case "new_notice": return "新通知";
                }
                break;
            case "ru":
                switch (key) {
                    case "ai_translate": return "AI-перевод";
                    case "translation": return "Перевод";
                    case "ai_subtitle": return "Родной язык · Простой корейский · Аудио";
                    case "analyzing": return "AI анализирует...";
                    case "analyzing_detail": return "AI анализирует...\n(Простой корейский → Родной язык → Аудио)";
                    case "timeout": return "Время анализа истекло.\nДлинные уведомления могут обрабатываться дольше.\n\nПопробуйте еще раз.";
                    case "server_error": return "Ошибка подключения к серверу";
                    case "todo": return "Что нужно сделать";
                    case "easy_korean": return "Простой корейский";
                    case "school_terms": return "Школьные термины";
                    case "listen": return "Слушать";
                    case "listen_easy_korean": return "Слушать простой корейский";
                    case "slow": return "Пословно";
                    case "normal": return "Медленно";
                    case "fast": return "Оригинал";
                    case "speak_to_ask": return "Спросить голосом";
                    case "back_to_notice": return "Назад к уведомлению";
                    case "refresh_inbox": return "Обновить";
                    case "logout": return "Выйти";
                    case "loading_inbox": return "Загрузка...";
                    case "empty_inbox": return "Уведомлений нет.";
                    case "received_notices": return "Полученные уведомления";
                    case "new_notice": return "Новые уведомления";
                }
                break;
            case "ms":
                switch (key) {
                    case "ai_translate": return "Terjemah AI";
                    case "translation": return "Terjemahan";
                    case "ai_subtitle": return "Bahasa ibunda · Korea mudah · Audio";
                    case "analyzing": return "AI sedang menganalisis...";
                    case "analyzing_detail": return "AI sedang menganalisis...\n(Korea mudah → Bahasa ibunda → Audio)";
                    case "timeout": return "Analisis tamat masa.\nNotis panjang mungkin mengambil masa.\n\nSila cuba lagi.";
                    case "server_error": return "Gagal sambung ke pelayan";
                    case "todo": return "Perlu dibuat";
                    case "easy_korean": return "Korea mudah";
                    case "school_terms": return "Istilah sekolah";
                    case "listen": return "Dengar";
                    case "listen_easy_korean": return "Dengar Korea mudah";
                    case "slow": return "Kata demi kata";
                    case "normal": return "Perlahan";
                    case "fast": return "Asal";
                    case "speak_to_ask": return "Tanya dengan suara";
                    case "back_to_notice": return "Kembali ke notis";
                    case "refresh_inbox": return "Muat semula";
                    case "logout": return "Log keluar";
                    case "loading_inbox": return "Memuatkan...";
                    case "empty_inbox": return "Tiada notis.";
                    case "received_notices": return "Notis diterima";
                    case "new_notice": return "Notis baharu";
                }
                break;
            case "mn":
                switch (key) {
                    case "ai_translate": return "AI орчуулга";
                    case "translation": return "Орчуулга";
                    case "ai_subtitle": return "Эх хэл · Хялбар солонгос · Аудио";
                    case "analyzing": return "AI шинжилж байна...";
                    case "analyzing_detail": return "AI шинжилж байна...\n(Хялбар солонгос → Эх хэл → Аудио)";
                    case "timeout": return "Шинжилгээний хугацаа дууслаа.\nУрт мэдэгдэл илүү удаж болно.\n\nДахин оролдоно уу.";
                    case "server_error": return "Сервертэй холбогдож чадсангүй";
                    case "todo": return "Хийх зүйл";
                    case "easy_korean": return "Хялбар солонгос";
                    case "school_terms": return "Сургуулийн үг";
                    case "listen": return "Сонсох";
                    case "listen_easy_korean": return "Хялбар солонгос сонсох";
                    case "slow": return "Үгээр үгд";
                    case "normal": return "Удаан";
                    case "fast": return "Эх";
                    case "speak_to_ask": return "Дуугаар асуух";
                    case "back_to_notice": return "Мэдэгдэл рүү буцах";
                    case "refresh_inbox": return "Дахин ачаалах";
                    case "logout": return "Гарах";
                    case "loading_inbox": return "Ачаалж байна...";
                    case "empty_inbox": return "Мэдэгдэл алга.";
                    case "received_notices": return "Ирсэн мэдэгдэл";
                    case "new_notice": return "Шинэ мэдэгдэл";
                }
                break;
            case "th":
                switch (key) {
                    case "ai_translate": return "แปลด้วย AI";
                    case "translation": return "คำแปล";
                    case "ai_subtitle": return "ภาษาแม่ · เกาหลีแบบง่าย · เสียง";
                    case "analyzing": return "AI กำลังวิเคราะห์...";
                    case "analyzing_detail": return "AI กำลังวิเคราะห์...\n(เกาหลีแบบง่าย → ภาษาแม่ → เสียง)";
                    case "timeout": return "หมดเวลาการวิเคราะห์\nประกาศยาวอาจใช้เวลานาน\n\nกรุณาลองอีกครั้ง";
                    case "server_error": return "เชื่อมต่อเซิร์ฟเวอร์ไม่สำเร็จ";
                    case "todo": return "สิ่งที่ต้องทำ";
                    case "easy_korean": return "เกาหลีแบบง่าย";
                    case "school_terms": return "คำศัพท์โรงเรียน";
                    case "listen": return "ฟัง";
                    case "listen_easy_korean": return "ฟังเกาหลีแบบง่าย";
                    case "slow": return "ทีละคำ";
                    case "normal": return "ช้า";
                    case "fast": return "ต้นฉบับ";
                    case "speak_to_ask": return "ถามด้วยเสียง";
                    case "back_to_notice": return "กลับไปประกาศ";
                    case "refresh_inbox": return "รีเฟรช";
                    case "logout": return "ออกจากระบบ";
                    case "loading_inbox": return "กำลังโหลด...";
                    case "empty_inbox": return "ยังไม่มีประกาศ";
                    case "received_notices": return "ประกาศที่ได้รับ";
                    case "new_notice": return "ประกาศใหม่";
                }
                break;
        }
        switch (key) {
            case "ai_translate": return "AI 번역";
            case "translation": return "번역";
            case "ai_subtitle": return "모국어 번역 · 쉬운 한국어 · 음성 안내";
            case "analyzing": return "AI가 분석 중입니다...";
            case "analyzing_detail": return "AI가 분석 중입니다...\n(쉬운 한국어 → 모국어 번역 → 음성 생성)";
            case "timeout": return "분석 시간이 초과되었습니다.\n긴 통신문은 처리 시간이 오래 걸릴 수 있습니다.\n\n잠시 후 다시 시도해 주세요.";
            case "server_error": return "서버 연결 실패";
            case "todo": return "해야 할 일";
            case "easy_korean": return "쉬운 한국어";
            case "school_terms": return "사용된 학교 용어";
            case "listen": return "듣기";
            case "listen_easy_korean": return "쉬운 한국어 듣기";
            case "slow": return "단어별";
            case "normal": return "천천히";
            case "fast": return "오리지날";
            case "speak_to_ask": return "말해서 물어보기";
            case "back_to_notice": return "통신문으로 돌아가기";
            case "refresh_inbox": return "수신함 새로고침";
            case "logout": return "로그아웃";
            case "loading_inbox": return "수신함을 불러오는 중...";
            case "empty_inbox": return "받은 가정통신문이 없습니다.";
            case "received_notices": return "받은 가정통신문";
            case "new_notice": return "새 통신문";
            default: return key;
        }
    }

    private String getSavedLanguage() {
        String lang = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .getString(PREF_KEY_LANG, "ko_easy");
        return isSupportedLanguage(lang) ? lang : "ko_easy";
    }

    private void saveLanguage(String langCode) {
        if (!isSupportedLanguage(langCode)) return;
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .edit()
                .putString(PREF_KEY_LANG, langCode)
                .apply();
    }

    // ============================================================
    //  인박스 NEW 뱃지 — user_id 별 seen notice_id 추적
    // ============================================================

    private String seenSetKey() {
        return PREF_SEEN_PREFIX + (currentUserId.isEmpty() ? "default" : currentUserId);
    }

    private String inboxInitKey() {
        return PREF_INBOX_INIT_PREFIX + (currentUserId.isEmpty() ? "default" : currentUserId);
    }

    private boolean isInboxInitialized() {
        return getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .getBoolean(inboxInitKey(), false);
    }

    private Set<String> getSeenNoticeIds() {
        // SharedPreferences.getStringSet 반환 객체 직접 수정 X — 새 HashSet 으로 복사.
        Set<String> stored = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .getStringSet(seenSetKey(), null);
        return stored == null ? new HashSet<>() : new HashSet<>(stored);
    }

    private void markNoticeSeen(String noticeId) {
        if (noticeId == null || noticeId.isEmpty()) return;
        Set<String> seen = getSeenNoticeIds();
        seen.add(noticeId);
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .edit()
                .putStringSet(seenSetKey(), seen)
                .apply();
    }

    private void markAllInboxSeen() {
        Set<String> seen = getSeenNoticeIds();
        for (NoticeItem n : inbox) {
            if (n != null && n.noticeId != null) seen.add(n.noticeId);
        }
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .edit()
                .putStringSet(seenSetKey(), seen)
                .putBoolean(inboxInitKey(), true)
                .apply();
    }

    // ============================================================
    //  Persistent login + FCM 토큰 등록
    // ============================================================

    /** 저장된 role + user_id 가 있으면 자동 로그인 → 홈으로 진입. 성공 시 true. */
    private boolean tryAutoLogin() {
        SharedPreferences prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        String userId = prefs.getString(PREF_USER_ID, "");
        String role   = prefs.getString(PREF_ROLE, "");
        if (userId.isEmpty() || role.isEmpty()) return false;
        currentUserId = userId;
        // 자동 진입 시점에도 알림 권한 + 토큰 등록 — 토큰이 만료/순환됐을 수 있어 매번 갱신.
        ensureNotificationPermission();
        fetchAndRegisterFcmToken();
        if (role.equals("teacher")) showTeacherHome();
        else showParentHome();
        return true;
    }

    private void saveLoginPrefs(String role, String userId) {
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .edit()
                .putString(PREF_USER_ID, userId)
                .putString(PREF_ROLE, role)
                .apply();
    }

    /** 로그아웃 — prefs 비우고, 백엔드에 FCM 토큰 등록 해제 + 화면 로그인으로. */
    private void logout() {
        String userId = currentUserId;
        SharedPreferences prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        prefs.edit().remove(PREF_USER_ID).remove(PREF_ROLE).apply();
        // 백엔드에서 토큰 제거 (실패해도 로그아웃은 진행)
        if (!userId.isEmpty()) {
            executor.submit(() -> sendUnregisterFcmToken(userId));
        }
        currentUserId = "";
        showLoginScreen();
    }

    /** Android 13+ — 알림 표시 권한 런타임 요청 (이전 버전은 권한 자동 부여). */
    private void ensureNotificationPermission() {
        if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.TIRAMISU) return;
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED) return;
        requestPermissions(
                new String[]{Manifest.permission.POST_NOTIFICATIONS},
                REQUEST_POST_NOTIFICATIONS);
    }

    /**
     * Firebase 에서 디바이스 토큰 받아서 백엔드 /notice/register-fcm-token 으로 등록.
     * 등록 실패해도 앱 사용은 계속 — 알림이 안 올 뿐.
     */
    private void fetchAndRegisterFcmToken() {
        if (currentUserId.isEmpty()) return;
        FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
            if (!task.isSuccessful() || task.getResult() == null) {
                android.util.Log.w("FCM", "getToken 실패: " + task.getException());
                return;
            }
            String token = task.getResult();
            getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                    .edit()
                    .putString(PREF_FCM_TOKEN, token)
                    .apply();
            executor.submit(() -> sendRegisterFcmToken(currentUserId, token, selectedLanguage));
        });
    }

    /** 백엔드 POST /notice/register-fcm-token */
    private void sendRegisterFcmToken(String userId, String token, String lang) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(BASE_URL + "/notice/register-fcm-token");
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setRequestProperty("X-User-Id", userId);
            conn.setDoOutput(true);
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(8000);
            JSONObject body = new JSONObject()
                    .put("user_id", userId)
                    .put("token", token)
                    .put("target_language", lang == null ? "ko" : lang);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }
            int code = conn.getResponseCode();
            android.util.Log.i("FCM", "register status=" + code + " user_id=" + userId);
        } catch (Exception error) {
            android.util.Log.w("FCM", "register 실패 user_id=" + userId + ": " + error);
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    /** 백엔드 DELETE /notice/register-fcm-token/{user_id} */
    private void sendUnregisterFcmToken(String userId) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(BASE_URL + "/notice/register-fcm-token/" + URLEncoder.encode(userId, "UTF-8"));
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("DELETE");
            conn.setRequestProperty("X-User-Id", userId);
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(8000);
            int code = conn.getResponseCode();
            android.util.Log.i("FCM", "unregister status=" + code + " user_id=" + userId);
        } catch (Exception error) {
            android.util.Log.w("FCM", "unregister 실패 user_id=" + userId + ": " + error);
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    /**
     * SchoolBridgeMessagingService.onNewToken() 에서 호출하는 정적 진입점.
     * 앱이 로그인 상태면 즉시 백엔드에 새 토큰 등록.
     */
    public static void tryRegisterFcmTokenFromService(Context ctx, String token) {
        SharedPreferences prefs = ctx.getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        String userId = prefs.getString(PREF_USER_ID, "");
        String lang   = prefs.getString(PREF_KEY_LANG, "ko");
        if (userId.isEmpty() || token == null || token.isEmpty()) return;
        // 백엔드 호출 — 짧은 스레드 (Service 생명주기는 길지 않음)
        new Thread(() -> {
            HttpURLConnection conn = null;
            try {
                URL url = new URL(BuildConfig.BASE_URL + "/notice/register-fcm-token");
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setRequestProperty("X-User-Id", userId);
                conn.setDoOutput(true);
                conn.setConnectTimeout(5000);
                conn.setReadTimeout(8000);
                JSONObject body = new JSONObject()
                        .put("user_id", userId)
                        .put("token", token)
                        .put("target_language", lang);
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(body.toString().getBytes(StandardCharsets.UTF_8));
                }
                int code = conn.getResponseCode();
                android.util.Log.i("FCM", "service-register status=" + code + " user_id=" + userId);
            } catch (Exception error) {
                android.util.Log.w("FCM", "service-register 실패: " + error);
            } finally {
                if (conn != null) conn.disconnect();
            }
        }).start();
    }

    private boolean isSupportedLanguage(String code) {
        if (code == null) return false;
        if (code.equals("ko_easy")) return true;
        for (String lang : LANG_CODES) {
            if (lang.equals(code)) return true;
        }
        return false;
    }

    private String optStringDeep(JSONObject object, String... keys) {
        if (object == null) return "";
        for (String key : keys) {
            String value = safeString(object, key);
            if (!value.isEmpty()) return value;
        }
        return "";
    }

    private String safeString(JSONObject object, String key) {
        if (object == null || key == null || object.isNull(key)) return "";
        String value = object.optString(key, "");
        if (value == null) return "";
        value = value.trim();
        return value.equalsIgnoreCase("null") ? "" : value;
    }

    private String firstNonBlank(String first, String second) {
        return first != null && !first.trim().isEmpty() ? first.trim() : safe(second);
    }

    private String firstNonBlank(String first, String second, String third) {
        if (first != null && !first.trim().isEmpty()) return first.trim();
        if (second != null && !second.trim().isEmpty()) return second.trim();
        return safe(third);
    }

    private String shorten(String value, int max) {
        String clean = value == null ? "" : value.replace('\n', ' ').trim();
        return clean.length() > max ? clean.substring(0, max) + "..." : clean;
    }

    private String safe(String value) {
        return value == null ? "" : value.trim();
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private int dp(float value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private void releasePlayer() {
        if (player != null) {
            try { player.release(); } catch (Exception ignored) {}
            player = null;
        }
    }

    private interface ApiCallback {
        void done(ApiResult result);
    }

    private static class ApiResult {
        String body = "";
        String error = "";
    }

    private static class NoticeItem {
        final String noticeId;
        final String teacherId;
        final String text;
        final String originalFileUrl;   // "/static/notices/{id}.pdf" 또는 null (텍스트 직송)
        final String originalFilename;  // "5월 가정통신문.pdf" 또는 null
        final String mimeType;          // "application/pdf" / "image/jpeg" 등 또는 null

        NoticeItem(String noticeId, String teacherId, String text,
                   String originalFileUrl, String originalFilename, String mimeType) {
            this.noticeId = noticeId;
            this.teacherId = teacherId;
            this.text = text;
            this.originalFileUrl = originalFileUrl;
            this.originalFilename = originalFilename;
            this.mimeType = mimeType;
        }

        boolean hasOriginalFile() {
            return originalFileUrl != null && !originalFileUrl.isEmpty();
        }

        boolean isPdf() {
            return "application/pdf".equalsIgnoreCase(mimeType)
                    || (originalFileUrl != null && originalFileUrl.toLowerCase().endsWith(".pdf"));
        }

        boolean isImage() {
            return mimeType != null && mimeType.toLowerCase().startsWith("image/");
        }
    }
}
