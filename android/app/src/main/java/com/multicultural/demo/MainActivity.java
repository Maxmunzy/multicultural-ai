package com.multicultural.demo;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
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
    private static final String BASE_URL = "http://192.168.45.93:8000";
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
    private TextView selectedNoticeText;
    private TextView analysisResultText;
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
        buildBase("\uAC00\uC815\uD1B5\uC2E0\uBB38 AI", "\uC2E4\uAE30\uAE30 MVP \uB370\uBAA8");
        content.addView(card("\uC2DC\uC5F0 \uD750\uB984", "1. \uC120\uC0DD\uB2D8\uC774 \uAC00\uC815\uD1B5\uC2E0\uBB38\uC744 \uBC1C\uC1A1\uD569\uB2C8\uB2E4.\n2. \uD559\uBD80\uBAA8\uAC00 \uC218\uC2E0\uD568\uC5D0\uC11C \uD655\uC778\uD569\uB2C8\uB2E4.\n3. \uBD84\uC11D \uACB0\uACFC, \uBC88\uC5ED, \uC6A9\uC5B4\uC0AC\uC804 \uAC80\uC218, TTS\uB97C \uD655\uC778\uD569\uB2C8\uB2E4.", Color.WHITE));
        content.addView(primaryButton("\uC120\uC0DD\uB2D8\uC73C\uB85C \uC2DC\uC791", v -> showTeacherScreen()));
        content.addView(outlineButton("\uD559\uBD80\uBAA8\uB85C \uC2DC\uC791", v -> showParentScreen()));
        setStatus("\uC11C\uBC84 IP\uB294 MainActivity.java \uC0C1\uB2E8 BASE_URL\uC5D0\uC11C \uBCC0\uACBD\uD569\uB2C8\uB2E4: " + BASE_URL);
    }

    private void showTeacherScreen() {
        buildBase("\uC120\uC0DD\uB2D8 \uD654\uBA74", "\uAC00\uC815\uD1B5\uC2E0\uBB38 \uBC1C\uC1A1");
        titleInput = input("\uC81C\uBAA9", "\uD604\uC7A5\uD559\uC2B5 \uC548\uB0B4");
        bodyInput = multiInput("\uAC00\uC815\uD1B5\uC2E0\uBB38 \uBCF8\uBB38", sampleNotice());
        parentIdInput = input("parent_id", DEFAULT_PARENT_ID);
        sendResultText = text("", 14, Color.rgb(71, 85, 105), false);

        content.addView(titleInput);
        content.addView(bodyInput);
        content.addView(parentIdInput);
        content.addView(primaryButton("\uBC1C\uC1A1", v -> sendNotice()));
        content.addView(outlineButton("\uC0D8\uD50C \uAC00\uC815\uD1B5\uC2E0\uBB38 \uCC44\uC6B0\uAE30", v -> fillSampleNotice()));
        content.addView(card("\uBC1C\uC1A1 \uACB0\uACFC", "\uC544\uC9C1 \uBC1C\uC1A1\uD558\uC9C0 \uC54A\uC558\uC2B5\uB2C8\uB2E4.", Color.WHITE));
        ((LinearLayout) content.getChildAt(content.getChildCount() - 1)).addView(sendResultText);
        content.addView(outlineButton("\uCC98\uC74C\uC73C\uB85C", v -> showStartScreen()));
        setStatus("POST /notice/send");
    }

    private void showParentScreen() {
        buildBase("\uD559\uBD80\uBAA8 \uD654\uBA74", "\uC218\uC2E0\uD568 + \uBD84\uC11D \uACB0\uACFC");
        inboxParentInput = input("parent_id", DEFAULT_PARENT_ID);
        inboxListText = text("\uC218\uC2E0\uD568\uC744 \uBD88\uB7EC\uC624\uC138\uC694.", 14, Color.rgb(71, 85, 105), false);
        selectedNoticeText = text("\uC120\uD0DD\uB41C \uAC00\uC815\uD1B5\uC2E0\uBB38\uC774 \uC5C6\uC2B5\uB2C8\uB2E4.", 14, Color.rgb(71, 85, 105), false);
        analysisResultText = text("\uBD84\uC11D \uACB0\uACFC\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.", 14, Color.rgb(30, 41, 59), false);
        analyzeButton = primaryButton("\uBD84\uC11D\uD558\uAE30", v -> analyzeSelectedNotice());
        playButton = primaryButton("\uBCA0\uD2B8\uB0A8\uC5B4 TTS \uC7AC\uC0DD", v -> playTts());

        content.addView(inboxParentInput);
        content.addView(primaryButton("\uC218\uC2E0\uD568 \uBD88\uB7EC\uC624\uAE30", v -> loadInbox()));
        content.addView(outlineButton("\uBAA9 \uC751\uB2F5 \uC5C6\uC744 \uB54C \uB370\uBAA8 \uACB0\uACFC \uBCF4\uAE30", v -> showMockAnalysis()));
        content.addView(cardWithView("\uAC00\uC815\uD1B5\uC2E0\uBB38 \uBAA9\uB85D", inboxListText, Color.WHITE));
        content.addView(cardWithView("\uC120\uD0DD\uD55C \uAC00\uC815\uD1B5\uC2E0\uBB38", selectedNoticeText, Color.rgb(245, 250, 255)));
        content.addView(analyzeButton);
        content.addView(cardWithView("\uBD84\uC11D \uACB0\uACFC", analysisResultText, Color.WHITE));
        content.addView(playButton);
        content.addView(outlineButton("\uCC98\uC74C\uC73C\uB85C", v -> showStartScreen()));
        setStatus("GET /notice/inbox/{parent_id} ? POST /notice/analyze/{notice_id}");
    }

    private void sendNotice() {
        String title = safe(titleInput.getText().toString());
        String body = safe(bodyInput.getText().toString());
        String parentId = safe(parentIdInput.getText().toString());
        if (parentId.isEmpty()) parentId = DEFAULT_PARENT_ID;
        if (body.isEmpty()) {
            setSendResult("\uBCF8\uBB38\uC744 \uC785\uB825\uD574\uC8FC\uC138\uC694.");
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

        setSendResult("\uBC1C\uC1A1 \uC911...");
        postJson("/notice/send", bodyJson, result -> {
            if (!result.error.isEmpty()) {
                setSendResult("\uC11C\uBC84 \uC5F0\uACB0 \uC2E4\uD328: " + result.error);
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                String noticeId = json.optJSONObject("data") == null ? "" : json.optJSONObject("data").optString("notice_id", "");
                setSendResult("\uBC1C\uC1A1 \uC644\uB8CC\nnotice_id: " + noticeId + "\n" + json.optString("message", ""));
            } catch (Exception error) {
                setSendResult("\uBC1C\uC1A1 \uC751\uB2F5 \uD30C\uC2F1 \uC2E4\uD328\n" + result.body);
            }
        });
    }

    private void loadInbox() {
        String parentId = safe(inboxParentInput.getText().toString());
        if (parentId.isEmpty()) parentId = DEFAULT_PARENT_ID;
        inboxListText.setText("\uC218\uC2E0\uD568 \uBD88\uB7EC\uC624\uB294 \uC911...");
        getJson("/notice/inbox/" + parentId, result -> {
            if (!result.error.isEmpty()) {
                inboxListText.setText("\uC11C\uBC84 \uC5F0\uACB0 \uC2E4\uD328\n" + result.error);
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                JSONArray data = json.optJSONArray("data");
                inbox.clear();
                if (data == null || data.length() == 0) {
                    inboxListText.setText("\uC218\uC2E0\uD55C \uAC00\uC815\uD1B5\uC2E0\uBB38\uC774 \uC5C6\uC2B5\uB2C8\uB2E4.");
                    selectedNotice = null;
                    selectedNoticeText.setText("\uC120\uD0DD\uB41C \uAC00\uC815\uD1B5\uC2E0\uBB38\uC774 \uC5C6\uC2B5\uB2C8\uB2E4.");
                    return;
                }
                StringBuilder listText = new StringBuilder();
                for (int i = 0; i < data.length(); i++) {
                    JSONObject item = data.getJSONObject(i);
                    NoticeItem notice = new NoticeItem(
                            item.optString("notice_id", ""),
                            item.optString("teacher_id", ""),
                            item.optString("text", "")
                    );
                    inbox.add(notice);
                    listText.append(i + 1).append(". ").append(shorten(notice.text)).append("\n");
                }
                selectedNotice = inbox.get(0);
                inboxListText.setText(listText.toString().trim() + "\n\n\uCCAB \uBC88\uC9F8 \uAC00\uC815\uD1B5\uC2E0\uBB38\uC744 \uC120\uD0DD\uD588\uC2B5\uB2C8\uB2E4.");
                selectedNoticeText.setText(selectedNotice.text);
            } catch (Exception error) {
                inboxListText.setText("\uC218\uC2E0\uD568 \uC751\uB2F5 \uD30C\uC2F1 \uC2E4\uD328\n" + result.body);
            }
        });
    }

    private void analyzeSelectedNotice() {
        if (selectedNotice == null || selectedNotice.noticeId.isEmpty()) {
            analysisResultText.setText("\uBD84\uC11D\uD560 \uAC00\uC815\uD1B5\uC2E0\uBB38\uC744 \uBA3C\uC800 \uC120\uD0DD\uD558\uC138\uC694.");
            return;
        }
        analysisResultText.setText("\uBD84\uC11D \uC911...");
        postJson("/notice/analyze/" + selectedNotice.noticeId, null, result -> {
            if (!result.error.isEmpty()) {
                analysisResultText.setText("\uC11C\uBC84 \uC5F0\uACB0 \uC2E4\uD328\n" + result.error + "\n\n\uACE0\uC815 \uB370\uBAA8 \uACB0\uACFC\uB97C \uD45C\uC2DC\uD569\uB2C8\uB2E4.");
                showMockAnalysis();
                return;
            }
            try {
                JSONObject json = new JSONObject(result.body);
                JSONObject data = json.optJSONObject("data");
                if (data == null) {
                    analysisResultText.setText("\uBD84\uC11D \uACB0\uACFC\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.");
                    return;
                }
                analysisResultText.setText(formatAnalysis(data));
                currentTtsUrl = optStringDeep(data, "tts_url", "tts_path", "audio_url");
            } catch (Exception error) {
                analysisResultText.setText("\uBD84\uC11D \uC751\uB2F5 \uD30C\uC2F1 \uC2E4\uD328\n" + result.body);
            }
        });
    }

    private String formatAnalysis(JSONObject data) {
        StringBuilder builder = new StringBuilder();
        JSONArray todos = data.optJSONArray("todos");
        builder.append("\uD575\uC2EC \uCCB4\uD06C\uB9AC\uC2A4\uD2B8\n");
        if (todos != null && todos.length() > 0) {
            for (int i = 0; i < todos.length(); i++) {
                JSONObject todo = todos.optJSONObject(i);
                if (todo == null) continue;
                builder.append("- ").append(todo.optString("text_ko", todo.toString())).append("\n");
                String vi = todo.optString("text_vi", "");
                if (!vi.isEmpty()) builder.append("  ").append(vi).append("\n");
            }
        } else {
            builder.append("\uBD84\uC11D \uACB0\uACFC\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.\n");
        }
        appendIfPresent(builder, "\n\uC26C\uC6B4 \uD55C\uAD6D\uC5B4\n", data, "easy_ko_text", "easy_korean");
        appendIfPresent(builder, "\n\uBCA0\uD2B8\uB0A8\uC5B4 \uBC88\uC5ED\n", data, "vi_text", "vietnamese", "translation_vi");
        appendIfPresent(builder, "\nGlossary check\n", data, "glossary_check", "quality_note");
        return builder.toString().trim();
    }

    private void showMockAnalysis() {
        String easyKo = readAsset("demo_case_01/01_easy_ko_input.txt");
        String rawVi = readAsset("demo_case_01/02_vi_raw_translation.txt");
        String glossary = readAsset("demo_case_01/03_glossary_check.csv");
        String review = readAsset("demo_case_01/04_review_needed.md");
        String correctedVi = readAsset("demo_case_01/05_vi_corrected_translation.txt");
        currentTtsUrl = "";
        analysisResultText.setText(
                "\uD575\uC2EC \uCCB4\uD06C\uB9AC\uC2A4\uD2B8\n" +
                "- \uBB3C\uBCD1\uACFC \uB3C4\uC2DC\uB77D \uC900\uBE44\n" +
                "- \uC624\uC804 9\uC2DC\uAE4C\uC9C0 \uD559\uAD50 \uC6B4\uB3D9\uC7A5 \uB3C4\uCC29\n\n" +
                "\uC26C\uC6B4 \uD55C\uAD6D\uC5B4\n" + easyKo + "\n" +
                "\uBCA0\uD2B8\uB0A8\uC5B4 \uBC88\uC5ED\n" + rawVi + "\n\n" +
                "Glossary check\n" + summarizeGlossary(glossary) + "\n\n" +
                "review_needed / missing_term\n" + compactReview(review) + "\n\n" +
                "\uBCF4\uC815 \uBC88\uC5ED\uBB38\n" + correctedVi
        );
    }

    private String summarizeGlossary(String csv) {
        if (TextUtils.isEmpty(csv)) return "\uAC80\uC218 \uACB0\uACFC\uB97C \uC77D\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4.";
        String[] lines = csv.split("\\r?\\n");
        if (lines.length < 2) return csv.trim();
        String row = lines[1];
        String[] cols = row.split(",", -1);
        if (cols.length >= 5) {
            return "missing_term \uAC10\uC9C0\n" + cols[0] + " -> " + cols[1] + "\nquality_label: " + cols[4];
        }
        return csv.trim();
    }

    private String compactReview(String review) {
        return review
                .replace("# Review Needed", "Review Needed")
                .replace("## ", "")
                .replace("```text", "")
                .replace("```", "")
                .trim();
    }

    private void playTts() {
        releasePlayer();
        try {
            if (!TextUtils.isEmpty(currentTtsUrl) && currentTtsUrl.startsWith("http")) {
                player = new MediaPlayer();
                player.setDataSource(currentTtsUrl);
                player.setOnPreparedListener(mp -> {
                    mp.start();
                    playButton.setText("\uC7AC\uC0DD \uC911... \uB2E4\uC2DC \uB204\uB974\uBA74 \uC815\uC9C0");
                });
                player.setOnCompletionListener(mp -> playButton.setText("\uBCA0\uD2B8\uB0A8\uC5B4 TTS \uC7AC\uC0DD"));
                player.prepareAsync();
            } else {
                player = MediaPlayer.create(this, R.raw.tts_output);
                player.start();
                playButton.setText("\uC7AC\uC0DD \uC911... \uB2E4\uC2DC \uB204\uB974\uBA74 \uC815\uC9C0");
                player.setOnCompletionListener(mp -> playButton.setText("\uBCA0\uD2B8\uB0A8\uC5B4 TTS \uC7AC\uC0DD"));
            }
        } catch (Exception error) {
            analysisResultText.setText(analysisResultText.getText() + "\n\nTTS \uC7AC\uC0DD \uC2E4\uD328: " + error.getMessage());
        }
    }

    private void fillSampleNotice() {
        titleInput.setText("\uD604\uC7A5\uD559\uC2B5 \uC548\uB0B4");
        bodyInput.setText(sampleNotice());
        parentIdInput.setText(DEFAULT_PARENT_ID);
    }

    private String sampleNotice() {
        return "\uB0B4\uC77C \uD604\uC7A5\uD559\uC2B5\uC774 \uC788\uC2B5\uB2C8\uB2E4.\n\uC544\uC774\uB294 \uBB3C\uBCD1\uACFC \uB3C4\uC2DC\uB77D\uC744 \uAC00\uC838\uC640 \uC8FC\uC138\uC694.\n\uC544\uCE68 9\uC2DC\uAE4C\uC9C0 \uD559\uAD50 \uC6B4\uB3D9\uC7A5\uC73C\uB85C \uC640 \uC8FC\uC138\uC694.";
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
                conn.setReadTimeout(10000);
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
            return "\uD30C\uC77C\uC744 \uC77D\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4: " + name + "\n" + error.getMessage();
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
