package com.multicultural.demo;

import android.app.Activity;
import android.app.Dialog;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.Button;
import android.widget.EditText;
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
    // On a real device, localhost means the phone itself. Use the PC Docker server IP on the same Wi-Fi.
    private static final String BASE_URL = "http://192.168.x.x:8000";
    private static final String DEFAULT_PARENT_ID = "parent_001";
    private static final String DEFAULT_TEACHER_ID = "teacher_001";
    private static final int COLOR_PRIMARY = Color.rgb(37, 99, 235);
    private static final int COLOR_PRIMARY_DARK = Color.rgb(30, 64, 175);
    private static final int COLOR_PRIMARY_LIGHT = Color.rgb(239, 246, 255);
    private static final int COLOR_BG = Color.rgb(248, 250, 252);
    private static final int COLOR_TEXT = Color.rgb(30, 41, 59);
    private static final int COLOR_MUTED = Color.rgb(100, 116, 139);
    private static final int COLOR_BORDER = Color.rgb(226, 232, 240);
    private static final int COLOR_SUCCESS = Color.rgb(16, 185, 129);

    private static final float TEXT_SIZE_MIN = 10f;
    private static final float TEXT_SIZE_MAX = 24f;
    private float currentTextSize = 14f;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final List<NoticeItem> inbox = new ArrayList<>();

    private LinearLayout root;
    private LinearLayout content;
    private TextView statusText;
    private EditText titleInput;
    private EditText bodyInput;
    private EditText parentIdInput;
    private EditText inboxParentInput;
    private TextView sendResultText;
    private TextView inboxListText;
    private LinearLayout inboxListBox;
    private TextView selectedNoticeText;
    private TextView analysisResultText;
    private TextView feedbackText;
    private LinearLayout layoutAnalysis;
    private LinearLayout layoutFeedback;
    private Button analyzeButton;
    private Button playButton;

    private NoticeItem selectedNotice;
    private MediaPlayer player;
    private String currentTtsUrl = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        showStartScreen();
    }

    private void showStartScreen() {
        buildBase("가정통신문 AI", "실기기 MVP 데모");
        content.addView(card("시연 흐름", "1. 선생님이 가정통신문을 발송합니다.\n2. 학부모가 수신함에서 확인합니다.\n3. 분석 결과, 번역, 용어사전 검수, TTS를 확인합니다.", Color.WHITE));
        content.addView(primaryButton("선생님으로 시작", v -> showTeacherScreen()));
        content.addView(outlineButton("학부모로 시작", v -> showParentScreen()));
        setStatus("서버 IP는 MainActivity.java 상단 BASE_URL에서 변경합니다: " + BASE_URL);
    }

    private void showTeacherScreen() {
        buildBase("선생님 화면", "가정통신문 발송");
        titleInput = input("제목", "현장학습 안내");
        bodyInput = multiInput("가정통신문 본문", sampleNotice());
        parentIdInput = input("parent_id", DEFAULT_PARENT_ID);
        sendResultText = text("", 14, Color.rgb(71, 85, 105), false);

        content.addView(titleInput);
        content.addView(bodyInput);
        content.addView(parentIdInput);
        content.addView(primaryButton("발송", v -> sendNotice()));
        content.addView(outlineButton("샘플 가정통신문 채우기", v -> fillSampleNotice()));
        content.addView(card("발송 결과", "아직 발송하지 않았습니다.", Color.WHITE));
        ((LinearLayout) content.getChildAt(content.getChildCount() - 1)).addView(sendResultText);
        content.addView(outlineButton("처음으로", v -> showStartScreen()));
        setStatus("POST /notice/send");
    }

    private void showParentScreen() {
        releasePlayer();
        setContentView(R.layout.activity_parent);

        statusText = findViewById(R.id.tvStatus);
        inboxParentInput = findViewById(R.id.etParentId);
        inboxListText = findViewById(R.id.tvInboxList);
        inboxListBox = findViewById(R.id.lvInboxList);
        selectedNoticeText = findViewById(R.id.tvSelectedNotice);
        analysisResultText = findViewById(R.id.tvAnalysisResult);
        feedbackText = findViewById(R.id.tvFeedback);
        layoutAnalysis = findViewById(R.id.layoutAnalysis);
        layoutFeedback = findViewById(R.id.layoutFeedback);
        analyzeButton = findViewById(R.id.btnAnalyze);
        playButton = findViewById(R.id.btnPlay);

        findViewById(R.id.btnLoadInbox).setOnClickListener(v -> loadInbox());
        findViewById(R.id.btnDemo).setOnClickListener(v -> showMockAnalysis());
        analyzeButton.setOnClickListener(v -> analyzeSelectedNotice());
        playButton.setOnClickListener(v -> playTts());
        findViewById(R.id.btnAiAssistant).setOnClickListener(v -> showAiBottomSheet());
        findViewById(R.id.btnBack).setOnClickListener(v -> showStartScreen());

        // 탭 전환
        findViewById(R.id.btnTabAnalysis).setOnClickListener(v -> switchTab(true));
        findViewById(R.id.btnTabFeedback).setOnClickListener(v -> switchTab(false));

        // 글씨 크기 조절
        findViewById(R.id.btnZoomIn).setOnClickListener(v -> adjustTextSize(2f));
        findViewById(R.id.btnZoomOut).setOnClickListener(v -> adjustTextSize(-2f));
        findViewById(R.id.btnZoomInFeedback).setOnClickListener(v -> adjustTextSize(2f));
        findViewById(R.id.btnZoomOutFeedback).setOnClickListener(v -> adjustTextSize(-2f));

        setStatus("수신함 조회와 분석 요청을 준비했습니다.");
    }

    private void switchTab(boolean showAnalysis) {
        layoutAnalysis.setVisibility(showAnalysis ? View.VISIBLE : View.GONE);
        layoutFeedback.setVisibility(showAnalysis ? View.GONE : View.VISIBLE);
    }

    private void adjustTextSize(float delta) {
        currentTextSize = Math.max(TEXT_SIZE_MIN, Math.min(TEXT_SIZE_MAX, currentTextSize + delta));
        if (analysisResultText != null) analysisResultText.setTextSize(currentTextSize);
        if (feedbackText != null) feedbackText.setTextSize(currentTextSize);
    }

    private void showAiBottomSheet() {
        Dialog dialog = new Dialog(this, R.style.BottomSheetTheme);
        View sheetView = getLayoutInflater().inflate(R.layout.bottom_sheet_ai, null);
        dialog.setContentView(sheetView);

        Window window = dialog.getWindow();
        if (window != null) {
            window.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            window.setGravity(Gravity.BOTTOM);
        }

        ScrollView scrollChat = sheetView.findViewById(R.id.scrollChat);
        LinearLayout chatContainer = sheetView.findViewById(R.id.chatContainer);
        LinearLayout quickQuestions = sheetView.findViewById(R.id.quickQuestions);
        EditText etInput = sheetView.findViewById(R.id.etChatInput);

        sheetView.<Button>findViewById(R.id.btnClose).setOnClickListener(v -> dialog.dismiss());
        sheetView.<Button>findViewById(R.id.btnSend).setOnClickListener(v ->
                sendChatMessage(chatContainer, scrollChat, etInput, null));

        addBotBubble(chatContainer, scrollChat, "안녕하세요! 가정통신문에 대해 궁금한 것을 물어보세요.");

        String[] quickList = {"번역해줘", "요약해줘", "할 일 뭐야?", "날짜 알려줘"};
        for (String q : quickList) {
            Button qBtn = new Button(this);
            qBtn.setText(q);
            qBtn.setTextSize(13);
            qBtn.setTextColor(COLOR_PRIMARY_DARK);
            qBtn.setAllCaps(false);
            qBtn.setPadding(dp(14), dp(8), dp(14), dp(8));
            qBtn.setBackgroundResource(R.drawable.bg_quick_btn);
            LinearLayout.LayoutParams qp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            qp.setMargins(0, 0, dp(8), 0);
            qBtn.setLayoutParams(qp);
            qBtn.setOnClickListener(v -> sendChatMessage(chatContainer, scrollChat, etInput, q));
            quickQuestions.addView(qBtn);
        }

        dialog.show();
    }

    private void sendChatMessage(LinearLayout container, ScrollView scroll, EditText input, String override) {
        String message = override != null ? override : safe(input.getText().toString());
        if (message.isEmpty()) return;
        input.setText("");

        addUserBubble(container, scroll, message);

        String context = selectedNotice != null ? selectedNotice.text : "";
        JSONObject payload = new JSONObject();
        try {
            payload.put("message", message);
            payload.put("context", context);
            payload.put("parent_id", DEFAULT_PARENT_ID);
        } catch (Exception e) {
            addBotBubble(container, scroll, "오류: " + e.getMessage());
            return;
        }

        addBotBubble(container, scroll, "답변 중...");
        postJson("/ai/chat", payload, result -> {
            if (container.getChildCount() > 0)
                container.removeViewAt(container.getChildCount() - 1);
            if (!result.error.isEmpty()) {
                addBotBubble(container, scroll, "서버 연결 실패: " + result.error);
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                String reply = optStringDeep(json, "reply", "message", "answer");
                addBotBubble(container, scroll, reply.isEmpty() ? "응답을 받지 못했습니다." : reply);
            } catch (Exception e) {
                addBotBubble(container, scroll, result.body.isEmpty() ? "응답을 받지 못했습니다." : result.body);
            }
        });
    }

    private void addUserBubble(LinearLayout container, ScrollView scroll, String msg) {
        TextView bubble = new TextView(this);
        bubble.setText(msg);
        bubble.setTextColor(Color.WHITE);
        bubble.setTextSize(14);
        bubble.setLineSpacing(0, 1.25f);
        bubble.setPadding(dp(12), dp(8), dp(12), dp(8));
        bubble.setBackgroundResource(R.drawable.bg_bubble_user);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        p.gravity = Gravity.END;
        p.setMargins(dp(48), 0, 0, dp(8));
        bubble.setLayoutParams(p);
        container.addView(bubble);
        scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
    }

    private void addBotBubble(LinearLayout container, ScrollView scroll, String msg) {
        TextView bubble = new TextView(this);
        bubble.setText(msg);
        bubble.setTextColor(COLOR_TEXT);
        bubble.setTextSize(14);
        bubble.setLineSpacing(0, 1.25f);
        bubble.setPadding(dp(12), dp(8), dp(12), dp(8));
        bubble.setBackgroundResource(R.drawable.bg_bubble_bot);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        p.gravity = Gravity.START;
        p.setMargins(0, 0, dp(48), dp(8));
        bubble.setLayoutParams(p);
        container.addView(bubble);
        scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
    }

    private void sendNotice() {
        String title = safe(titleInput.getText().toString());
        String body = safe(bodyInput.getText().toString());
        String parentId = safe(parentIdInput.getText().toString());
        if (parentId.isEmpty()) parentId = DEFAULT_PARENT_ID;
        if (body.isEmpty()) {
            setSendResult("본문을 입력해주세요.");
            return;
        }
        String payloadText = title.isEmpty() ? body : title + "\n" + body;
        JSONObject bodyJson = new JSONObject();
        try {
            bodyJson.put("teacher_id", DEFAULT_TEACHER_ID);
            bodyJson.put("parent_id", parentId);
            bodyJson.put("text", payloadText);
        } catch (Exception error) {
            setSendResult(error.getMessage());
            return;
        }

        setSendResult("발송 중...");
        postJson("/notice/send", bodyJson, result -> {
            if (!result.error.isEmpty()) {
                setSendResult("서버 연결 실패: " + result.error);
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                String noticeId = json.optJSONObject("data") == null ? "" : json.optJSONObject("data").optString("notice_id", "");
                setSendResult("발송 완료\nnotice_id: " + noticeId + "\n" + json.optString("message", ""));
            } catch (Exception error) {
                setSendResult("발송 응답 파싱 실패\n" + result.body);
            }
        });
    }

    private void loadInbox() {
        String parentId = safe(inboxParentInput.getText().toString());
        if (parentId.isEmpty()) parentId = DEFAULT_PARENT_ID;
        resetInboxList("수신함 불러오는 중...");
        getJson("/notice/inbox/" + parentId, result -> {
            if (!result.error.isEmpty()) {
                resetInboxList("서버 연결 실패\n" + result.error);
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                JSONArray data = json.optJSONArray("data");
                inbox.clear();
                if (data == null || data.length() == 0) {
                    resetInboxList("수신한 가정통신문이 없습니다.");
                    selectedNotice = null;
                    selectedNoticeText.setText("선택된 가정통신문이 없습니다.");
                    return;
                }
                for (int i = 0; i < data.length(); i++) {
                    JSONObject item = data.getJSONObject(i);
                    NoticeItem notice = new NoticeItem(
                            item.optString("notice_id", ""),
                            item.optString("teacher_id", ""),
                            item.optString("text", "")
                    );
                    inbox.add(notice);
                }
                renderInboxList();
                selectNotice(0);
            } catch (Exception error) {
                resetInboxList("수신함 응답 파싱 실패\n" + result.body);
            }
        });
    }

    private void renderInboxList() {
        inboxListBox.removeAllViews();
        inboxListText.setVisibility(View.GONE);
        for (int i = 0; i < inbox.size(); i++) {
            final int index = i;
            NoticeItem notice = inbox.get(i);
            Button itemButton = outlineButton((i + 1) + ". " + shorten(notice.text), v -> selectNotice(index));
            inboxListBox.addView(itemButton);
        }
    }

    private void selectNotice(int index) {
        if (index < 0 || index >= inbox.size()) return;
        selectedNotice = inbox.get(index);
        selectedNoticeText.setText(selectedNotice.text);
        analysisResultText.setText("분석하기를 누르면 결과를 볼 수 있습니다.");
        feedbackText.setText("분석 후 피드백이 표시됩니다.");
        currentTtsUrl = "";
        setStatus((index + 1) + "번 가정통신문을 선택했습니다.");
    }

    private void resetInboxList(String message) {
        inboxListBox.removeAllViews();
        inboxListText.setVisibility(View.VISIBLE);
        inboxListText.setText(message);
    }

    private void analyzeSelectedNotice() {
        if (selectedNotice == null || selectedNotice.noticeId.isEmpty()) {
            analysisResultText.setText("분석할 가정통신문을 먼저 선택하세요.");
            return;
        }
        analysisResultText.setText("분석 중...");
        feedbackText.setText("분석 중...");
        postJson("/notice/analyze/" + selectedNotice.noticeId, null, result -> {
            if (!result.error.isEmpty()) {
                analysisResultText.setText("서버 연결 실패\n" + result.error + "\n\n고정 데모 결과를 표시합니다.");
                showMockAnalysis();
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                JSONObject data = json.optJSONObject("data");
                if (data == null) {
                    analysisResultText.setText("분석 결과가 없습니다.");
                    feedbackText.setText("피드백 결과가 없습니다.");
                    return;
                }
                analysisResultText.setText(formatMain(data));
                feedbackText.setText(formatFeedback(data));
                currentTtsUrl = optStringDeep(data, "tts_url", "tts_path", "audio_url");
            } catch (Exception error) {
                analysisResultText.setText("분석 응답 파싱 실패\n" + result.body);
            }
        });
    }

    private String formatMain(JSONObject data) {
        StringBuilder builder = new StringBuilder();
        JSONArray todos = data.optJSONArray("todos");
        builder.append("해야 할 일\n");
        if (todos != null && todos.length() > 0) {
            for (int i = 0; i < todos.length(); i++) {
                JSONObject todo = todos.optJSONObject(i);
                if (todo == null) continue;
                builder.append("- ").append(todo.optString("text_ko", todo.toString())).append("\n");
            }
        } else {
            builder.append("분석 결과가 없습니다.\n");
        }
        appendIfPresent(builder, "\n쉬운 한국어\n", data, "easy_ko_text", "easy_korean");
        String finalVi = optStringDeep(data, "corrected_vi_text", "corrected_translation", "vi_corrected_translation", "final_vi_text", "vi_text", "vietnamese", "translation_vi");
        if (!finalVi.isEmpty()) {
            builder.append("\n베트남어 번역\n").append(finalVi).append('\n');
        }
        return builder.toString().trim();
    }

    private String formatFeedback(JSONObject data) {
        StringBuilder builder = new StringBuilder();
        String glossary = optStringDeep(data, "glossary_check", "quality_note");
        if (!glossary.isEmpty()) {
            builder.append("용어 확인\n").append(parentGlossarySummary(glossary)).append("\n\n");
        }
        String review = optStringDeep(data, "review_needed", "review_note", "glossary_review");
        if (!review.isEmpty()) {
            builder.append("검수 상세\n").append(compactReview(review)).append('\n');
        }
        return builder.length() == 0 ? "피드백 항목이 없습니다." : builder.toString().trim();
    }

    private void showMockAnalysis() {
        String easyKo = readAsset("demo_case_01/01_easy_ko_input.txt");
        String rawVi = readAsset("demo_case_01/02_vi_raw_translation.txt");
        String glossary = readAsset("demo_case_01/03_glossary_check.csv");
        String review = readAsset("demo_case_01/04_review_needed.md");
        String correctedVi = readAsset("demo_case_01/05_vi_corrected_translation.txt");
        currentTtsUrl = "";
        analysisResultText.setText(
                "핵심 체크리스트\n" +
                "- 물병과 도시락 준비\n" +
                "- 오전 9시까지 학교 운동장 도착\n\n" +
                "쉬운 한국어\n" + easyKo + "\n" +
                "베트남어 번역\n" + correctedVi
        );
        feedbackText.setText(
                "용어 확인\n" + summarizeGlossary(glossary) + "\n\n" +
                "검수 상세\n" + compactReview(review) + "\n\n" +
                "참고: 원번역\n" + rawVi
        );
    }

    private String summarizeGlossary(String csv) {
        if (TextUtils.isEmpty(csv)) return "검수 결과를 읽지 못했습니다.";
        String[] lines = csv.split("\\r?\\n");
        if (lines.length < 2) return csv.trim();
        String row = lines[1];
        String[] cols = row.split(",", -1);
        if (cols.length >= 5) {
            return cols[0] + " 누락 감지 → 보정 번역문에 반영됨";
        }
        return parentGlossarySummary(csv);
    }

    private String compactReview(String review) {
        String clean = review
                .replace("# Review Needed", "Review Needed")
                .replace("## ", "")
                .replace("```text", "")
                .replace("```", "")
                .replace("missing_term", "누락된 용어")
                .replace("quality_label", "검수 결과")
                .trim();
        return clean.length() > 420 ? clean.substring(0, 420) + "\n..." : clean;
    }

    private String parentGlossarySummary(String value) {
        if (TextUtils.isEmpty(value)) return "용어 확인 결과가 없습니다.";
        if (value.contains("도시락") || value.contains("cơm hộp")) {
            return "도시락 누락 감지 → 보정 번역문에 반영됨";
        }
        if (value.toLowerCase().contains("missing")) {
            return "필요한 학교 용어를 확인했습니다.";
        }
        return "학교 용어를 확인했습니다.";
    }

    private void playTts() {
        releasePlayer();
        try {
            if (!TextUtils.isEmpty(currentTtsUrl)) {
                String dataSourceUrl = currentTtsUrl.startsWith("http")
                        ? currentTtsUrl
                        : BASE_URL + currentTtsUrl;
                player = new MediaPlayer();
                player.setDataSource(dataSourceUrl);
                player.setOnPreparedListener(mp -> {
                    mp.start();
                    playButton.setText("재생 중... 다시 누르면 정지");
                });
                player.setOnCompletionListener(mp -> playButton.setText("베트남어로 듣기"));
                player.prepareAsync();
            } else {
                player = MediaPlayer.create(this, R.raw.tts_output);
                player.start();
                playButton.setText("재생 중... 다시 누르면 정지");
                player.setOnCompletionListener(mp -> playButton.setText("베트남어로 듣기"));
            }
        } catch (Exception error) {
            analysisResultText.setText(analysisResultText.getText() + "\n\nTTS 재생 실패: " + error.getMessage());
        }
    }

    private void fillSampleNotice() {
        titleInput.setText("현장학습 안내");
        bodyInput.setText(sampleNotice());
        parentIdInput.setText(DEFAULT_PARENT_ID);
    }

    private String sampleNotice() {
        return "내일 현장학습이 있습니다.\n아이는 물병과 도시락을 가져와 주세요.\n아침 9시까지 학교 운동장으로 와 주세요.";
    }

    private void buildBase(String title, String subtitle) {
        releasePlayer();
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(COLOR_BG);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(0, 0, 0, dp(28));
        scroll.addView(root);

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setPadding(dp(20), dp(38), dp(20), dp(22));
        GradientDrawable headerBg = new GradientDrawable(
                GradientDrawable.Orientation.LEFT_RIGHT,
                new int[]{COLOR_PRIMARY_DARK, COLOR_PRIMARY}
        );
        headerBg.setCornerRadii(new float[]{0, 0, 0, 0, 0, 0, dp(22), dp(22)});
        header.setBackground(headerBg);

        LinearLayout headerTop = new LinearLayout(this);
        headerTop.setOrientation(LinearLayout.HORIZONTAL);
        headerTop.setGravity(Gravity.CENTER_VERTICAL);
        TextView titleView = text(title, 24, Color.WHITE, true);
        LinearLayout.LayoutParams titleParams = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        headerTop.addView(titleView, titleParams);
        TextView badge = pill("VI", Color.argb(45, 255, 255, 255), Color.WHITE);
        headerTop.addView(badge);
        header.addView(headerTop);

        TextView sub = text(subtitle, 14, Color.argb(220, 255, 255, 255), false);
        sub.setPadding(0, dp(6), 0, 0);
        header.addView(sub);
        root.addView(header);

        LinearLayout statusBox = new LinearLayout(this);
        statusBox.setOrientation(LinearLayout.VERTICAL);
        statusBox.setPadding(dp(18), dp(14), dp(18), 0);
        statusText = pill("", COLOR_PRIMARY_LIGHT, COLOR_PRIMARY_DARK);
        statusBox.addView(statusText);
        root.addView(statusBox);

        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(18), dp(4), dp(18), 0);
        root.addView(content);
        setContentView(scroll);
    }

    private EditText input(String hint, String value) {
        EditText edit = new EditText(this);
        edit.setHint(hint);
        edit.setText(value);
        edit.setSingleLine(true);
        edit.setTextSize(15);
        edit.setTextColor(COLOR_TEXT);
        edit.setHintTextColor(Color.rgb(148, 163, 184));
        edit.setPadding(dp(14), dp(10), dp(14), dp(10));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(14));
        bg.setStroke(dp(1), COLOR_BORDER);
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

    private Button primaryButton(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(15);
        button.setTextColor(Color.WHITE);
        button.setAllCaps(false);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setPadding(dp(14), dp(12), dp(14), dp(12));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(COLOR_PRIMARY);
        bg.setCornerRadius(dp(15));
        button.setBackground(bg);
        button.setOnClickListener(listener);
        button.setLayoutParams(spacedParams());
        return button;
    }

    private Button outlineButton(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(15);
        button.setAllCaps(false);
        button.setTextColor(COLOR_PRIMARY_DARK);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setPadding(dp(14), dp(12), dp(14), dp(12));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(COLOR_PRIMARY_LIGHT);
        bg.setCornerRadius(dp(15));
        bg.setStroke(dp(1), Color.rgb(191, 219, 254));
        button.setBackground(bg);
        button.setOnClickListener(listener);
        button.setLayoutParams(spacedParams());
        return button;
    }

    private LinearLayout card(String heading, String body, int bgColor) {
        return cardWithView(heading, text(body.trim(), 15, Color.rgb(30, 41, 59), false), bgColor);
    }

    private LinearLayout cardWithView(String heading, View bodyView, int bgColor) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(16), dp(16), dp(16), dp(16));
        box.setLayoutParams(spacedParams());
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(bgColor);
        drawable.setCornerRadius(dp(18));
        drawable.setStroke(dp(1), COLOR_BORDER);
        box.setBackground(drawable);
        TextView h = text(heading, 13, COLOR_MUTED, true);
        h.setAllCaps(false);
        h.setPadding(0, 0, 0, dp(10));
        box.addView(h);
        box.addView(bodyView);
        return box;
    }

    private LinearLayout.LayoutParams spacedParams() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        params.setMargins(0, 0, 0, dp(12));
        return params;
    }

    private TextView pill(String value, int bgColor, int textColor) {
        TextView view = text(value, 12, textColor, true);
        view.setPadding(dp(12), dp(6), dp(12), dp(6));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(bgColor);
        bg.setCornerRadius(dp(18));
        bg.setStroke(dp(1), Color.argb(80, 255, 255, 255));
        view.setBackground(bg);
        return view;
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

    private String readAsset(String name) {
        StringBuilder builder = new StringBuilder();
        try (InputStream stream = getAssets().open(name);
             BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) builder.append(line).append('\n');
        } catch (Exception error) {
            return "파일을 읽지 못했습니다: " + name + "\n" + error.getMessage();
        }
        return builder.toString();
    }

    private void appendIfPresent(StringBuilder builder, String heading, JSONObject data, String... keys) {
        for (String key : keys) {
            String value = data.optString(key, "");
            if (!value.isEmpty()) {
                builder.append(heading).append(value).append('\n');
                return;
            }
        }
    }

    private String optStringDeep(JSONObject object, String... keys) {
        for (String key : keys) {
            String value = object.optString(key, "");
            if (!value.isEmpty()) return value;
        }
        return "";
    }

    private String shorten(String value) {
        String clean = value.replace('\n', ' ').trim();
        return clean.length() > 42 ? clean.substring(0, 42) + "..." : clean;
    }

    private String safe(String value) {
        return value == null ? "" : value.trim();
    }

    private void setStatus(String value) {
        statusText.setText(value);
    }

    private void setSendResult(String value) {
        sendResultText.setText(value);
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private void releasePlayer() {
        if (player != null) {
            player.release();
            player = null;
        }
    }

    @Override
    protected void onDestroy() {
        releasePlayer();
        executor.shutdownNow();
        super.onDestroy();
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
