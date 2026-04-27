package com.multicultural.demo;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.os.Bundle;
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
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final String BASE_URL = "http://172.30.1.73:8000";
    private static final String DEFAULT_PARENT_ID = "parent_001";
    private static final String DEFAULT_TEACHER_ID = "teacher_001";

    // ── Daon design tokens ──
    private static final int COLOR_PEACH        = Color.parseColor("#FFD9C2");
    private static final int COLOR_PEACH_DEEP   = Color.parseColor("#FF9D6E");
    private static final int COLOR_PEACH_INK    = Color.parseColor("#B35A2B");
    private static final int COLOR_MINT         = Color.parseColor("#C8ECD9");
    private static final int COLOR_MINT_DEEP    = Color.parseColor("#6FCFA1");
    private static final int COLOR_MINT_INK     = Color.parseColor("#2F7A55");
    private static final int COLOR_LEMON        = Color.parseColor("#FFEAA3");
    private static final int COLOR_LEMON_INK    = Color.parseColor("#8A6A14");
    private static final int COLOR_LAVENDER     = Color.parseColor("#E3DCFB");
    private static final int COLOR_LAVENDER_INK = Color.parseColor("#5A4A99");
    private static final int COLOR_SKY          = Color.parseColor("#D4EBFF");
    private static final int COLOR_PAPER        = Color.parseColor("#FFFAF3");
    private static final int COLOR_PAPER2       = Color.parseColor("#FFF3E6");
    private static final int COLOR_INK          = Color.parseColor("#2B2018");
    private static final int COLOR_INK2         = Color.parseColor("#5A4A3D");
    private static final int COLOR_INK3         = Color.parseColor("#8A7C70");
    private static final int COLOR_INK4         = Color.parseColor("#C4B6A8");
    private static final int COLOR_LINE         = Color.parseColor("#EAD9C4");

    private static final String[] LANG_CODES  = {"ko_easy", "en", "ru", "ms", "mn", "vi", "zh", "th", "ja"};
    private static final String[] LANG_LABELS = {"🇰🇷 쉬운 한국어", "🇺🇸 영어", "🇷🇺 러시아어", "🇲🇾 말레이시아어", "🇲🇳 몽골어", "🇻🇳 베트남어", "🇨🇳 중국어", "🇹🇭 태국어", "🇯🇵 일본어"};
    private static final String[] LANG_NAMES  = {"쉬운 한국어", "영어", "러시아어", "말레이시아어", "몽골어", "베트남어", "중국어", "태국어", "일본어"};
    private static final String[] LANG_FLAGS  = {"KR", "EN", "RU", "MY", "MN", "VN", "CN", "TH", "JP"};
    private static final String[] LANG_NATIVE = {"쉬운 한국어", "English", "Русский", "Bahasa", "Монгол", "Tiếng Việt", "中文", "ไทย", "日本語"};

    private static String selectedLanguage = "vi";
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
    private Button playButton;
    private Button langPillBtn;

    private NoticeItem selectedNotice;
    private MediaPlayer player;
    private String currentTtsUrl = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        showLoginScreen();
    }

    @Override
    protected void onDestroy() {
        releasePlayer();
        executor.shutdownNow();
        super.onDestroy();
    }

    private void clearScreenRefs() {
        loginIdInput = null;
        titleInput = null;
        bodyInput = null;
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
                if (role.equals("teacher")) showTeacherHome();
                else showParentHome();
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

    // ============================================================
    //  SCREEN 2 · TEACHER HOME  (가통문 작성/발송)
    // ============================================================
    private void showTeacherHome() {
        clearScreenRefs();
        buildScreen("안녕하세요,", currentUserId + "님 ✏️",
                    "통신문 작성", true, 1, false);

        // 빠른 템플릿 chips (시각적 — 첫번째 탭하면 샘플 채우기)
        content.addView(sectionLabel("템플릿"));
        HorizontalScrollView chipScroll = new HorizontalScrollView(this);
        chipScroll.setHorizontalScrollBarEnabled(false);
        chipScroll.setLayoutParams(spacedParams());
        LinearLayout chipRow = new LinearLayout(this);
        chipRow.setOrientation(LinearLayout.HORIZONTAL);
        chipRow.addView(templateChip("📢 현장학습", true,  v -> fillSampleNotice()));
        chipRow.addView(templateChip("📅 상담",    false, null));
        chipRow.addView(templateChip("🍱 급식",    false, null));
        chipRow.addView(templateChip("📝 평가",    false, null));
        chipRow.addView(templateChip("+ 직접",     false, null));
        chipScroll.addView(chipRow);
        content.addView(chipScroll);

        // 받는 학부모
        content.addView(formCard("받는 학부모", () -> {
            parentIdInput = input("parent_001", DEFAULT_PARENT_ID);
            return parentIdInput;
        }));

        // 제목
        content.addView(formCard("제목", () -> {
            titleInput = input("예: 현장학습 안내", "현장학습 안내");
            titleInput.setBackground(transparentBg());
            titleInput.setPadding(0, dp(2), 0, dp(2));
            titleInput.setTextSize(17);
            titleInput.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
            return titleInput;
        }));

        // 내용
        content.addView(formCard("내용 (한국어)", () -> {
            bodyInput = multiInput("가정통신문 본문", sampleNotice());
            bodyInput.setBackground(transparentBg());
            bodyInput.setPadding(0, dp(2), 0, dp(2));
            bodyInput.setTextSize(14);
            return bodyInput;
        }));

        // AI 헬프 카드 (정보용 — 클릭 안 됨)
        content.addView(aiHelperCard());

        // 발송 결과
        sendResultText = text("", 13, COLOR_INK3, false);
        sendResultText.setVisibility(View.GONE);
        sendResultText.setLineSpacing(0, 1.45f);
        sendResultText.setPadding(dp(4), dp(4), dp(4), 0);
        content.addView(sendResultText);

        // 발송 CTA (full width primary)
        content.addView(bigPrimaryButton("📤  통신문 발송", v -> sendNotice()));
        content.addView(outlineButton("← 로그아웃", v -> showLoginScreen()));
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
        if (listener != null) {
            chip.setClickable(true);
            chip.setOnClickListener(listener);
        }
        LinearLayout wrap = new LinearLayout(this);
        wrap.addView(chip);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        p.setMargins(0, 0, dp(6), 0);
        wrap.setLayoutParams(p);
        return wrap;
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
        buildScreen("Xin chào,", currentUserId + "님 👋",
                    "받은 가정통신문", true, 0, true);

        inboxListBox = new LinearLayout(this);
        inboxListBox.setOrientation(LinearLayout.VERTICAL);
        inboxListBox.setLayoutParams(spacedParams());
        content.addView(sectionLabel("새 통신문"));
        content.addView(inboxListBox);

        inboxEmptyText = text("수신함을 불러오는 중...", 13, COLOR_INK3, false);
        inboxEmptyText.setPadding(dp(4), dp(8), dp(4), 0);
        inboxListBox.addView(inboxEmptyText);

        content.addView(outlineButton("🔄  수신함 새로고침", v -> loadInbox()));
        content.addView(outlineButton("← 로그아웃", v -> showLoginScreen()));

        loadInbox();
    }

    private void loadInbox() {
        inbox.clear();
        if (inboxEmptyText != null) {
            inboxEmptyText.setVisibility(View.VISIBLE);
            inboxEmptyText.setText("수신함을 불러오는 중...");
        }
        if (inboxListBox != null) {
            int childCount = inboxListBox.getChildCount();
            for (int i = childCount - 1; i >= 0; i--) {
                if (inboxListBox.getChildAt(i) != inboxEmptyText) inboxListBox.removeViewAt(i);
            }
        }
        getJson("/notice/inbox/" + currentUserId, result -> {
            if (!result.error.isEmpty()) {
                if (inboxEmptyText != null) inboxEmptyText.setText("서버 연결 실패\n" + result.error);
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                JSONArray data = json.optJSONArray("data");
                if (data == null || data.length() == 0) {
                    if (inboxEmptyText != null) inboxEmptyText.setText("받은 가정통신문이 없습니다.");
                    return;
                }
                for (int i = 0; i < data.length(); i++) {
                    JSONObject item = data.getJSONObject(i);
                    inbox.add(new NoticeItem(
                            item.optString("notice_id", ""),
                            item.optString("teacher_id", ""),
                            item.optString("text", "")
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
        String[] avatarEmojis = {"🍱", "📅", "📢", "🏃", "📝", "📖"};
        int[] avatarColors  = {COLOR_MINT, COLOR_LAVENDER, COLOR_PEACH, COLOR_LEMON, COLOR_SKY, COLOR_PAPER2};
        int[] avatarInks    = {COLOR_MINT_INK, COLOR_LAVENDER_INK, COLOR_PEACH_INK, COLOR_LEMON_INK, Color.parseColor("#1F5B8A"), COLOR_INK3};
        for (int i = 0; i < inbox.size(); i++) {
            NoticeItem n = inbox.get(i);
            String emoji = avatarEmojis[i % avatarEmojis.length];
            int avatarBg = avatarColors[i % avatarColors.length];
            int avatarInk = avatarInks[i % avatarInks.length];
            inboxListBox.addView(noticeListCard(n, emoji, avatarBg, avatarInk));
        }
    }

    private LinearLayout noticeListCard(NoticeItem n, String emoji, int avatarBg, int avatarInk) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.HORIZONTAL);
        box.setGravity(Gravity.CENTER_VERTICAL);
        box.setPadding(dp(14), dp(13), dp(14), dp(13));
        box.setLayoutParams(spacedParams());
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(16));
        bg.setStroke(dp(1), COLOR_LINE);
        box.setBackground(bg);
        box.setElevation(dp(0.5f));
        box.setClickable(true);
        box.setFocusable(true);
        box.setOnClickListener(v -> showNoticeDetail(n));

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

        // unread dot
        View dot = new View(this);
        GradientDrawable db = new GradientDrawable();
        db.setShape(GradientDrawable.OVAL);
        db.setColor(COLOR_PEACH_DEEP);
        dot.setBackground(db);
        LinearLayout.LayoutParams dp_ = new LinearLayout.LayoutParams(dp(8), dp(8));
        dot.setLayoutParams(dp_);
        box.addView(dot);
        return box;
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
        TextView titleView = text(title, 22, COLOR_INK, true);
        titleView.setLetterSpacing(-0.02f);
        titleView.setLineSpacing(0, 1.2f);
        titleView.setPadding(dp(2), 0, dp(2), dp(4));
        content.addView(titleView);

        TextView sender = text("👩‍🏫 " + notice.teacherId, 12, COLOR_INK3, false);
        sender.setPadding(dp(2), 0, 0, dp(14));
        content.addView(sender);

        // 한국어 원문 (paper card)
        TextView body = text(notice.text, 14, COLOR_INK, false);
        body.setLineSpacing(0, 1.65f);
        content.addView(cardWithView("한국어 원문", body, Color.WHITE));

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
        b.setText("✨ AI 번역");
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
        // mock — 클릭 안 함
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, weight);
        b.setLayoutParams(p);
        return b;
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
        root.setPadding(0, 0, 0, dp(28));
        scroll.addView(root);

        // 탑 액션 바: ✕ 닫기  (spacer)  🌐 lang pill
        LinearLayout topBar = new LinearLayout(this);
        topBar.setOrientation(LinearLayout.HORIZONTAL);
        topBar.setGravity(Gravity.CENTER_VERTICAL);
        topBar.setPadding(dp(14), dp(38), dp(14), dp(8));

        Button close = iconButton("✕", v -> showNoticeDetail(notice));
        topBar.addView(close);

        TextView center = text("AI 번역", 13, COLOR_INK2, true);
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

        TextView title = text(languageDisplayName(selectedLanguage) + " 번역",
                22, COLOR_INK, true);
        title.setLetterSpacing(-0.02f);
        title.setPadding(dp(2), 0, dp(2), dp(2));
        content.addView(title);

        TextView sub = text("쉬운 한국어 · 모국어 번역 · 음성 안내", 12, COLOR_INK3, false);
        sub.setPadding(dp(2), 0, 0, dp(12));
        content.addView(sub);

        // 글자 크기 조절
        content.addView(textSizeControls());

        // 분석 진행 상태 (먼저 보임 → 결과 도착하면 GONE)
        analysisStatusText = text("AI가 분석 중입니다...", 13, COLOR_INK3, false);
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
        LinearLayout checklistCard = cardWithView("📋  해야 할 일", checklistText, COLOR_PEACH);
        checklistCard.setVisibility(View.GONE);
        content.addView(checklistCard);

        // 쉬운 한국어
        easyKoText = text("", (int) currentTextSize, COLOR_INK, false);
        easyKoText.setLineSpacing(0, 1.6f);
        LinearLayout easyKoCard = cardWithView("🇰🇷  쉬운 한국어", easyKoText, Color.WHITE);
        easyKoCard.setVisibility(View.GONE);
        content.addView(easyKoCard);

        // 모국어 번역
        translationText = text("", (int) currentTextSize, COLOR_INK, false);
        translationText.setLineSpacing(0, 1.6f);
        String langHeading = LANG_FLAGS[langIndex(selectedLanguage)] + "  " +
                LANG_NATIVE[langIndex(selectedLanguage)];
        LinearLayout transCard = cardWithView(langHeading, translationText, Color.WHITE);
        transCard.setVisibility(View.GONE);
        content.addView(transCard);

        // 학교 용어 chips (lemon)
        glossaryChipsBox = new LinearLayout(this);
        glossaryChipsBox.setOrientation(LinearLayout.VERTICAL);
        glossaryChipsBox.setVisibility(View.GONE);
        LinearLayout glossaryWrap = cardWithView("📖  사용된 학교 용어", glossaryChipsBox, COLOR_LEMON);
        glossaryWrap.setVisibility(View.GONE);
        content.addView(glossaryWrap);

        // TTS 듣기 버튼
        playButton = bigPrimaryButton("🔊  " + LANG_NATIVE[langIndex(selectedLanguage)] + " 듣기",
                v -> playTts());
        playButton.setVisibility(View.GONE);
        content.addView(playButton);

        // 닫기
        content.addView(outlineButton("← 통신문으로 돌아가기", v -> showNoticeDetail(notice)));

        // refs to cards for visibility toggling
        easyKoCard.setTag("easyKoCard");
        transCard.setTag("transCard");
        checklistCard.setTag("checklistCard");
        glossaryWrap.setTag("glossaryWrap");
        statusCard.setTag("statusCard");

        outer.addView(scroll);
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
            analysisStatusText.setText("AI가 분석 중입니다...\n(쉬운 한국어 → 모국어 번역 → 음성 생성)");
        }
        toggleResultCards(false);

        JSONObject payload = new JSONObject();
        try { payload.put("target_language", selectedLanguage); } catch (Exception ignored) {}
        postJson("/notice/analyze/" + selectedNotice.noticeId, payload, result -> {
            if (!result.error.isEmpty()) {
                if (analysisStatusText != null)
                    analysisStatusText.setText("서버 연결 실패\n" + result.error +
                            "\n\n오프라인 데모 결과를 표시합니다.");
                showMockAnalysis();
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
        // 체크리스트
        JSONArray todos = data.optJSONArray("todos");
        StringBuilder cb = new StringBuilder();
        if (todos != null && todos.length() > 0) {
            for (int i = 0; i < todos.length(); i++) {
                JSONObject t = todos.optJSONObject(i);
                if (t == null) continue;
                cb.append("✓  ").append(t.optString("text_ko", t.toString())).append('\n');
            }
        }
        String checklist = cb.toString().trim();
        if (checklistText != null && !checklist.isEmpty()) {
            checklistText.setText(checklist);
            ((View) checklistText.getParent()).setVisibility(View.VISIBLE);
        }

        // 쉬운 한국어
        String easyKo = optStringDeep(data, "easy_ko_text", "easy_korean");
        if (easyKoText != null && !easyKo.isEmpty()) {
            easyKoText.setText(easyKo);
            ((View) easyKoText.getParent()).setVisibility(View.VISIBLE);
        }

        // 모국어 번역
        String translation = getTranslationForLanguage(data, selectedLanguage);
        if (translationText != null) {
            String quality = data.optString("quality_note", "");
            if (selectedLanguage.equals("ko_easy")) {
                translationText.setText("(쉬운 한국어 모드입니다 — 위 카드를 참고하세요)");
                translationText.setTextColor(COLOR_INK3);
            } else if (!translation.isEmpty()) {
                translationText.setText(highlightGlossary(translation, quality));
                translationText.setTextColor(COLOR_INK);
                ((View) translationText.getParent()).setVisibility(View.VISIBLE);
            }
        }

        // 학교 용어 chips
        String quality = data.optString("quality_note", "");
        if (glossaryChipsBox != null && !TextUtils.isEmpty(quality)) {
            glossaryChipsBox.removeAllViews();
            int added = 0;
            for (String pair : quality.split("[;\n]")) {
                String[] parts = pair.split("->");
                if (parts.length < 2) continue;
                String ko = parts[0].trim();
                String tgt = parts[1].trim();
                if (ko.isEmpty() || tgt.isEmpty()) continue;
                glossaryChipsBox.addView(glossaryChipRow(ko, tgt));
                added++;
                if (added >= 5) break;
            }
            if (added > 0) {
                ((View) glossaryChipsBox.getParent()).setVisibility(View.VISIBLE);
                ((View) glossaryChipsBox.getParent().getParent()).setVisibility(View.VISIBLE);
            }
        }

        // TTS
        currentTtsUrl = optStringDeep(data, "tts_url", "tts_path", "audio_url");
        if (playButton != null) {
            playButton.setText("🔊  " + LANG_NATIVE[langIndex(selectedLanguage)] + " 듣기");
            playButton.setVisibility(View.VISIBLE);
        }

        // status hide
        if (analysisStatusText != null) {
            View statusCard = (View) analysisStatusText.getParent();
            statusCard.setVisibility(View.GONE);
        }
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
                    || s.equals("checklistCard") || s.equals("glossaryWrap")) {
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
    // ============================================================
    private void sendNotice() {
        String title = safe(titleInput.getText().toString());
        String body = safe(bodyInput.getText().toString());
        String teacherId = currentUserId;
        String parentIdRaw = safe(parentIdInput.getText().toString());
        final String parentId = parentIdRaw.isEmpty() ? DEFAULT_PARENT_ID : parentIdRaw;
        if (body.isEmpty()) {
            setSendResult("⚠️ 본문을 입력해주세요.", false);
            return;
        }
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
                String noticeId = data == null ? "" : data.optString("notice_id", "");
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

    private String sampleNotice() {
        return "내일 현장학습이 있습니다.\n아이는 물병과 도시락을 가져와 주세요.\n아침 9시까지 학교 운동장으로 와 주세요.";
    }

    // ============================================================
    //  TTS
    // ============================================================
    private void playTts() {
        if (player != null) {
            try {
                if (player.isPlaying()) {
                    player.stop();
                    releasePlayer();
                    if (playButton != null)
                        playButton.setText("🔊  " + LANG_NATIVE[langIndex(selectedLanguage)] + " 듣기");
                    return;
                }
            } catch (IllegalStateException ignored) { }
        }
        releasePlayer();
        try {
            if (!TextUtils.isEmpty(currentTtsUrl)) {
                String url = currentTtsUrl.startsWith("http") ? currentTtsUrl : BASE_URL + currentTtsUrl;
                player = new MediaPlayer();
                player.setDataSource(url);
                player.setOnPreparedListener(mp -> {
                    mp.start();
                    if (playButton != null) playButton.setText("⏸  정지");
                });
                player.setOnCompletionListener(mp -> {
                    if (playButton != null)
                        playButton.setText("🔊  " + LANG_NATIVE[langIndex(selectedLanguage)] + " 듣기");
                    releasePlayer();
                });
                player.prepareAsync();
            } else {
                player = MediaPlayer.create(this, R.raw.tts_output);
                player.start();
                if (playButton != null) playButton.setText("⏸  정지");
                player.setOnCompletionListener(mp -> {
                    if (playButton != null)
                        playButton.setText("🔊  " + LANG_NATIVE[langIndex(selectedLanguage)] + " 듣기");
                    releasePlayer();
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

    // ============================================================
    //  LANG PILL  (top-right)
    // ============================================================
    private Button makeLangPillButton() {
        Button b = new Button(this);
        int idx = langIndex(selectedLanguage);
        b.setText("🌐  " + LANG_NATIVE[idx] + "  ▾");
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
        builder.setTitle("번역 언어 선택");
        builder.setItems(LANG_LABELS, (dialog, which) -> {
            if (LANG_CODES[which].equals(selectedLanguage)) return;
            selectedLanguage = LANG_CODES[which];
            if (langPillBtn != null) {
                int idx = langIndex(selectedLanguage);
                langPillBtn.setText("🌐  " + LANG_NATIVE[idx] + "  ▾");
            }
            releasePlayer();
            currentTtsUrl = "";
            // AI 화면이면 자동 재분석
            if (selectedNotice != null && analysisStatusText != null) {
                showAIOverlay(selectedNotice);
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
                conn.setConnectTimeout(5000);
                conn.setReadTimeout(60000);
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
            case "ko_easy": return "";
            case "en": return optStringDeep(data, "en_text", "english", "translation_en");
            case "ru": return optStringDeep(data, "ru_text", "russian", "translation_ru");
            case "ms": return optStringDeep(data, "ms_text", "malay", "translation_ms");
            case "mn": return optStringDeep(data, "mn_text", "mongolian", "translation_mn");
            case "vi": return optStringDeep(data, "corrected_vi_text", "corrected_translation",
                    "vi_corrected_translation", "final_vi_text", "vi_text", "vietnamese", "translation_vi");
            case "zh": return optStringDeep(data, "zh_text", "chinese", "translation_zh");
            case "th": return optStringDeep(data, "th_text", "thai", "translation_th");
            case "ja": return optStringDeep(data, "ja_text", "japanese", "translation_ja");
            default: return "";
        }
    }

    private String languageDisplayName(String code) {
        for (int i = 0; i < LANG_CODES.length; i++) {
            if (LANG_CODES[i].equals(code)) return LANG_NAMES[i];
        }
        return code;
    }

    private String optStringDeep(JSONObject object, String... keys) {
        for (String key : keys) {
            String value = object.optString(key, "");
            if (!value.isEmpty()) return value;
        }
        return "";
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

        NoticeItem(String noticeId, String teacherId, String text) {
            this.noticeId = noticeId;
            this.teacherId = teacherId;
            this.text = text;
        }
    }
}
