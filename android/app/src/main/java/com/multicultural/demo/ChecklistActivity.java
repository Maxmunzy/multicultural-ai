package com.multicultural.demo;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 통합 체크리스트 화면 — parent의 모든 통신문의 행동 항목 한 곳에 모음.
 *
 * 백엔드 GET /notice/inbox/{parent_id}/checklist 응답 파싱 → chip별 탭(준비물/제출/
 * 비용/건강·안전) + 마감일순 평면 리스트 탭. 각 항목 체크박스 토글 → POST
 * /notice/checklist/{notice_id} (stable card_id/item_id 사용).
 *
 * MainActivity에서 진입할 때 EXTRA_PARENT_ID 필수 (target_lang은 옵션).
 */
public class ChecklistActivity extends Activity {
    public static final String EXTRA_PARENT_ID   = "parent_id";
    public static final String EXTRA_TARGET_LANG = "target_lang";

    private static final String BASE_URL = BuildConfig.BASE_URL;

    // MainActivity 디자인 토큰과 동일 (peach/mint/lemon 톤)
    private static final int COLOR_PEACH       = Color.parseColor("#FFD9C2");
    private static final int COLOR_PEACH_DEEP  = Color.parseColor("#FF9D6E");
    private static final int COLOR_PEACH_INK   = Color.parseColor("#B35A2B");
    private static final int COLOR_PAPER       = Color.parseColor("#FFFAF3");
    private static final int COLOR_PAPER2      = Color.parseColor("#FFF3E6");
    private static final int COLOR_INK         = Color.parseColor("#2B2018");
    private static final int COLOR_INK2        = Color.parseColor("#5A4A3D");
    private static final int COLOR_INK3        = Color.parseColor("#8A7C70");
    private static final int COLOR_LINE        = Color.parseColor("#EAD9C4");
    private static final int COLOR_MINT_INK    = Color.parseColor("#2F7A55");
    private static final int COLOR_LEMON_INK   = Color.parseColor("#8A6A14");

    // 탭 — chip 4개 + 마감일순 평면. by_chip의 키 그대로 사용.
    private static final String TAB_DUE = "__due__";
    private static final List<String> TAB_ORDER = Arrays.asList(
            "준비물", "제출", "비용", "건강·안전", TAB_DUE
    );

    // {keyword, drawable_name, description}
    // drawable_name: res/drawable/supply_*.png 로 추가하면 자동 표시, 없으면 placeholder
    private static final String[][] SUPPLIES_DATA = {
        {"리코더",      "supply_recorder",          "음악 시간에 사용하는 작은 피리 모양 악기입니다. 녹음기가 아닙니다."},
        {"클리어 화일", "supply_clear_file",         "종이를 넣어 보관하는 투명한 파일입니다."},
        {"유성매직",    "supply_permanent_marker",   "잘 지워지지 않는 진한 펜입니다. 이름 쓰기나 표시할 때 씁니다."},
        {"사인펜",      "supply_felt_pen",           "색칠하거나 글씨를 쓸 때 쓰는 색 펜입니다."},
        {"크레파스",    "supply_crayon",             "색칠할 때 쓰는 색깔 막대입니다."},
        {"도화지",      "supply_drawing_paper",      "그림을 그릴 때 쓰는 두꺼운 종이입니다."},
        {"찰흙",        "supply_clay",               "손으로 모양을 만들 수 있는 점토입니다."},
        {"붓",          "supply_brush",              "물감으로 그림을 그릴 때 쓰는 도구입니다."},
        {"실내화",      "supply_indoor_shoes",       "교실이나 학교 건물 안에서 신는 신발입니다."},
        {"물통",        "supply_water_bottle",       "물을 담아 가지고 다니는 개인 물병입니다."},
    };

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private String parentId = "";
    private String targetLang = "ko_easy";
    private LinearLayout tabBar;
    private LinearLayout container;
    private TextView statusText;
    private String currentTab = "준비물";
    private JSONObject lastByChip = null;
    private JSONArray lastByDueDate = null;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent intent = getIntent();
        if (intent != null) {
            parentId = nullSafe(intent.getStringExtra(EXTRA_PARENT_ID));
            targetLang = nullSafe(intent.getStringExtra(EXTRA_TARGET_LANG));
        }
        if (parentId.isEmpty()) {
            Toast.makeText(this, "parent_id가 비어있습니다", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }
        if (targetLang.isEmpty()) targetLang = "ko_easy";
        setContentView(buildLayout());
        loadChecklist();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        executor.shutdownNow();
    }

    // ── Layout ──────────────────────────────────────────────────────────────

    private View buildLayout() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(COLOR_PAPER);

        // top bar — ← back + title
        LinearLayout topBar = new LinearLayout(this);
        topBar.setOrientation(LinearLayout.HORIZONTAL);
        topBar.setGravity(Gravity.CENTER_VERTICAL);
        topBar.setPadding(dp(16), dp(14), dp(16), dp(10));

        TextView back = text("←", 22, COLOR_INK, true);
        back.setPadding(dp(6), dp(2), dp(14), dp(2));
        back.setOnClickListener(v -> finish());
        topBar.addView(back);

        TextView title = text("📋  이번 주 할 일", 18, COLOR_INK, true);
        topBar.addView(title);
        root.addView(topBar);

        // tab bar — horizontal scroll for chips
        HorizontalScrollView tabScroll = new HorizontalScrollView(this);
        tabScroll.setHorizontalScrollBarEnabled(false);
        tabBar = new LinearLayout(this);
        tabBar.setOrientation(LinearLayout.HORIZONTAL);
        tabBar.setPadding(dp(12), 0, dp(12), dp(8));
        tabScroll.addView(tabBar);
        root.addView(tabScroll);

        // status (loading / empty)
        statusText = text("불러오는 중…", 14, COLOR_INK3, false);
        statusText.setPadding(dp(20), dp(20), dp(20), dp(20));
        root.addView(statusText);

        // entries scroll
        ScrollView scroll = new ScrollView(this);
        scroll.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setPadding(dp(14), dp(4), dp(14), dp(28));
        scroll.addView(container);
        root.addView(scroll);

        return root;
    }

    private void rebuildTabs(int[] counts) {
        tabBar.removeAllViews();
        for (int i = 0; i < TAB_ORDER.size(); i++) {
            String tab = TAB_ORDER.get(i);
            String label = tabLabel(tab);
            if (counts != null && i < counts.length) {
                label += " (" + counts[i] + ")";
            }
            tabBar.addView(tabChip(tab, label, tab.equals(currentTab)));
        }
    }

    private TextView tabChip(String key, String label, boolean active) {
        TextView t = new TextView(this);
        t.setText(label);
        t.setTextSize(13);
        t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        t.setTextColor(active ? COLOR_PEACH_INK : COLOR_INK2);
        t.setPadding(dp(14), dp(8), dp(14), dp(8));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(active ? Color.WHITE : COLOR_PAPER2);
        bg.setStroke(dp(active ? 2 : 1), active ? COLOR_PEACH_DEEP : COLOR_LINE);
        bg.setCornerRadius(dp(999));
        t.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.rightMargin = dp(8);
        t.setLayoutParams(lp);
        t.setOnClickListener(v -> {
            currentTab = key;
            renderTab();
        });
        return t;
    }

    private String tabLabel(String key) {
        switch (key) {
            case "준비물":    return "📦 준비물";
            case "제출":      return "📝 제출";
            case "비용":      return "💰 비용";
            case "건강·안전": return "🛡 건강";
            case TAB_DUE:     return "⌛ 마감일순";
        }
        return key;
    }

    // ── Load + render ───────────────────────────────────────────────────────

    private void loadChecklist() {
        executor.submit(() -> {
            String body = "";
            String error = null;
            HttpURLConnection conn = null;
            try {
                URL url = new URL(BASE_URL + "/notice/inbox/" + parentId + "/checklist");
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("GET");
                conn.setConnectTimeout(30000);
                conn.setReadTimeout(30000);
                conn.setRequestProperty("Accept", "application/json");
                conn.setRequestProperty("X-User-Id", parentId);
                int code = conn.getResponseCode();
                InputStream stream = code >= 200 && code < 300
                        ? conn.getInputStream() : conn.getErrorStream();
                body = readStream(stream);
                if (code < 200 || code >= 300) {
                    error = "HTTP " + code + "\n" + body;
                }
            } catch (Exception ex) {
                error = ex.getMessage() == null ? ex.toString() : ex.getMessage();
            } finally {
                if (conn != null) conn.disconnect();
            }
            String finalBody = body;
            String finalError = error;
            runOnUiThread(() -> applyResponse(finalBody, finalError));
        });
    }

    private void applyResponse(String body, String error) {
        if (error != null) {
            statusText.setVisibility(View.VISIBLE);
            statusText.setText("불러오기 실패: " + error);
            return;
        }
        try {
            JSONObject root = new JSONObject(body);
            JSONObject data = root.optJSONObject("data");
            if (data == null) {
                statusText.setVisibility(View.VISIBLE);
                statusText.setText("응답 데이터가 비어있습니다");
                return;
            }
            lastByChip = data.optJSONObject("by_chip");
            lastByDueDate = data.optJSONArray("by_due_date");
            statusText.setVisibility(View.GONE);

            int[] counts = new int[TAB_ORDER.size()];
            for (int i = 0; i < TAB_ORDER.size(); i++) {
                String tab = TAB_ORDER.get(i);
                if (TAB_DUE.equals(tab)) {
                    counts[i] = lastByDueDate != null ? lastByDueDate.length() : 0;
                } else {
                    JSONArray arr = lastByChip != null ? lastByChip.optJSONArray(tab) : null;
                    counts[i] = arr != null ? arr.length() : 0;
                }
            }
            // 빈 탭은 첫 비-빈 탭으로 자동 이동 (UX)
            int curIdx = TAB_ORDER.indexOf(currentTab);
            if (curIdx < 0 || counts[curIdx] == 0) {
                for (int i = 0; i < TAB_ORDER.size(); i++) {
                    if (counts[i] > 0) { currentTab = TAB_ORDER.get(i); break; }
                }
            }
            rebuildTabs(counts);
            renderTab();
        } catch (Exception ex) {
            statusText.setVisibility(View.VISIBLE);
            statusText.setText("파싱 실패: " + ex.getMessage());
        }
    }

    private void renderTab() {
        container.removeAllViews();
        int[] counts = new int[TAB_ORDER.size()];
        for (int i = 0; i < TAB_ORDER.size(); i++) {
            String tab = TAB_ORDER.get(i);
            if (TAB_DUE.equals(tab)) {
                counts[i] = lastByDueDate != null ? lastByDueDate.length() : 0;
            } else {
                JSONArray arr = lastByChip != null ? lastByChip.optJSONArray(tab) : null;
                counts[i] = arr != null ? arr.length() : 0;
            }
        }
        rebuildTabs(counts);

        JSONArray entries;
        boolean showDue = TAB_DUE.equals(currentTab);
        if (showDue) {
            entries = lastByDueDate;
        } else {
            entries = lastByChip != null ? lastByChip.optJSONArray(currentTab) : null;
        }

        if (entries == null || entries.length() == 0) {
            TextView empty = text("체크할 항목이 없습니다", 14, COLOR_INK3, false);
            empty.setPadding(0, dp(40), 0, 0);
            empty.setGravity(Gravity.CENTER);
            container.addView(empty);
            return;
        }
        for (int i = 0; i < entries.length(); i++) {
            JSONObject entry = entries.optJSONObject(i);
            if (entry != null) container.addView(buildEntryCard(entry, showDue));
        }
    }

    private View buildEntryCard(JSONObject entry, boolean showDue) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(14));
        bg.setStroke(dp(1), COLOR_LINE);
        card.setBackground(bg);
        card.setPadding(dp(16), dp(14), dp(16), dp(14));
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        cp.bottomMargin = dp(10);
        card.setLayoutParams(cp);

        // top row: notice_title (small) + due_date chip (right, optional)
        LinearLayout topRow = new LinearLayout(this);
        topRow.setOrientation(LinearLayout.HORIZONTAL);
        topRow.setGravity(Gravity.CENTER_VERTICAL);

        String noticeTitle = entry.optString("notice_title", "");
        TextView titleTv = text(noticeTitle, 12, COLOR_INK3, false);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        titleTv.setLayoutParams(tlp);
        titleTv.setMaxLines(1);
        titleTv.setEllipsize(android.text.TextUtils.TruncateAt.END);
        topRow.addView(titleTv);

        String dueDate = entry.optString("due_date", "");
        if (!dueDate.isEmpty() && !"null".equals(dueDate)) {
            TextView dueChip = text("⌛ " + dueDate, 11, COLOR_PEACH_INK, true);
            dueChip.setPadding(dp(8), dp(3), dp(8), dp(3));
            GradientDrawable dueBg = new GradientDrawable();
            dueBg.setColor(COLOR_PEACH);
            dueBg.setCornerRadius(dp(999));
            dueChip.setBackground(dueBg);
            topRow.addView(dueChip);
        }
        card.addView(topRow);

        // header_ko (large)
        String headerKo = entry.optString("header_ko", "");
        String headerTranslated = entry.optString("header_translated", "");
        String entryChip = entry.optString("chip", "");
        boolean isSuppliesCard = "준비물".equals(entryChip);
        // D: "기타" 헤더는 칩 카테고리 이름으로 대체
        if ("기타".equals(headerKo) && !entryChip.isEmpty() && !TAB_DUE.equals(entryChip)) {
            headerKo = entryChip;
        }
        // F: 비한국어 언어 선택 시 번역된 헤더 우선
        String displayHeader = (!targetLang.equals("ko_easy") && !headerTranslated.isEmpty())
                ? headerTranslated : headerKo;
        TextView header = text(displayHeader, 16, COLOR_INK, true);
        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hlp.topMargin = dp(4);
        header.setLayoutParams(hlp);
        card.addView(header);

        // value_ko (small)
        String valueKo = entry.optString("value_ko", "");
        if (!valueKo.isEmpty() && !valueKo.equals(headerKo)) {
            TextView val = text(valueKo, 12, COLOR_INK2, false);
            LinearLayout.LayoutParams vlp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            vlp.topMargin = dp(2);
            val.setLayoutParams(vlp);
            val.setMaxLines(2);
            val.setEllipsize(android.text.TextUtils.TruncateAt.END);
            val.setAlpha(0.75f);
            card.addView(val);
        }

        // progress
        JSONArray cl = entry.optJSONArray("checklist");
        TextView progress = text("", 12, COLOR_MINT_INK, true);
        LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        plp.topMargin = dp(8);
        progress.setLayoutParams(plp);
        card.addView(progress);

        // checkbox list
        if (cl != null) {
            String noticeId = entry.optString("notice_id");
            String cardKind = entry.optString("card_kind");
            String cardId = entry.optString("card_id");
            for (int i = 0; i < cl.length(); i++) {
                JSONObject item = cl.optJSONObject(i);
                if (item == null) continue;
                CheckBox cb = new CheckBox(this);
                String ko = item.optString("ko", "");
                String translatedLabel = item.optString("translated", "");
                // F: 비한국어 언어는 번역 라벨 우선, 없으면 ko 폴백
                String label = (!targetLang.equals("ko_easy") && !translatedLabel.isEmpty())
                        ? translatedLabel : ko;
                if (label.isEmpty()) label = ko;
                String note = item.optString("note", "");
                if (!note.isEmpty() && !"null".equals(note)) {
                    label += "  (" + note + ")";
                }
                cb.setText(label);
                cb.setTextSize(14);
                cb.setTextColor(COLOR_INK);
                cb.setChecked(item.optBoolean("checked", false));
                LinearLayout.LayoutParams cblp = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                cblp.topMargin = dp(2);
                cb.setLayoutParams(cblp);

                String itemId = item.optString("item_id");
                final JSONObject itemRef = item;
                cb.setOnCheckedChangeListener((v, isChecked) -> {
                    try { itemRef.put("checked", isChecked); } catch (Exception ignored) {}
                    updateProgress(progress, cl);
                    toggleItem(noticeId, cardKind, cardId, itemId, isChecked);
                });
                card.addView(cb);
                // C: 준비물 카드에서만 이미지 힌트 표시
                if (isSuppliesCard) {
                    View hint = buildSuppliesHint(ko);
                    if (hint != null) card.addView(hint);
                }
            }
        }

        updateProgress(progress, cl);
        return card;
    }

    private void updateProgress(TextView progress, JSONArray cl) {
        int total = cl != null ? cl.length() : 0;
        int done = 0;
        if (cl != null) {
            for (int i = 0; i < cl.length(); i++) {
                JSONObject it = cl.optJSONObject(i);
                if (it != null && it.optBoolean("checked", false)) done++;
            }
        }
        progress.setText(done + "/" + total + " 완료");
        progress.setTextColor(done == total && total > 0 ? COLOR_MINT_INK : COLOR_LEMON_INK);
    }

    // ── HTTP toggle ─────────────────────────────────────────────────────────

    private void toggleItem(String noticeId, String cardKind, String cardId,
                             String itemId, boolean checked) {
        executor.submit(() -> {
            HttpURLConnection conn = null;
            try {
                URL url = new URL(BASE_URL + "/notice/checklist/" + noticeId);
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setConnectTimeout(30000);
                conn.setReadTimeout(30000);
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setRequestProperty("Accept", "application/json");
                conn.setRequestProperty("X-User-Id", parentId);

                JSONObject body = new JSONObject();
                body.put("card_kind", cardKind);
                body.put("card_id", cardId);
                body.put("item_id", itemId);
                body.put("checked", checked);
                conn.getOutputStream().write(body.toString().getBytes(StandardCharsets.UTF_8));

                int code = conn.getResponseCode();
                if (code < 200 || code >= 300) {
                    final String errBody = readStream(conn.getErrorStream());
                    runOnUiThread(() -> Toast.makeText(this,
                            "토글 실패 HTTP " + code + ": " + errBody,
                            Toast.LENGTH_SHORT).show());
                }
            } catch (Exception ex) {
                final String msg = ex.getMessage() == null ? ex.toString() : ex.getMessage();
                runOnUiThread(() -> Toast.makeText(this,
                        "토글 오류: " + msg, Toast.LENGTH_SHORT).show());
            } finally {
                if (conn != null) conn.disconnect();
            }
        });
    }

    // ── Helpers ─────────────────────────────────────────────────────────────

    private View buildSuppliesHint(String itemText) {
        if (itemText == null || itemText.isEmpty()) return null;
        String normText = itemText.replaceAll("\\s+", "");
        LinearLayout box = null;
        int count = 0;
        for (String[] s : SUPPLIES_DATA) {
            if (count >= 3) break;
            if (!normText.contains(s[0].replaceAll("\\s+", ""))) continue;
            if (box == null) {
                box = new LinearLayout(this);
                box.setOrientation(LinearLayout.VERTICAL);
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                lp.topMargin = dp(6);
                box.setLayoutParams(lp);
            }
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            GradientDrawable rowBg = new GradientDrawable();
            rowBg.setColor(Color.parseColor("#F5F0EA"));
            rowBg.setCornerRadius(dp(10));
            row.setBackground(rowBg);
            row.setPadding(dp(10), dp(8), dp(10), dp(8));
            LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            if (count > 0) rlp.topMargin = dp(4);
            row.setLayoutParams(rlp);

            int imgSize = dp(56);
            int resId = getResources().getIdentifier(
                    s[1], "drawable", getPackageName());
            if (resId != 0) {
                ImageView img = new ImageView(this);
                img.setImageResource(resId);
                img.setScaleType(ImageView.ScaleType.CENTER_CROP);
                GradientDrawable imgBg = new GradientDrawable();
                imgBg.setColor(Color.WHITE);
                imgBg.setCornerRadius(dp(8));
                img.setBackground(imgBg);
                LinearLayout.LayoutParams ilp = new LinearLayout.LayoutParams(imgSize, imgSize);
                ilp.rightMargin = dp(10);
                img.setLayoutParams(ilp);
                row.addView(img);
            } else {
                LinearLayout ph = new LinearLayout(this);
                ph.setOrientation(LinearLayout.VERTICAL);
                ph.setGravity(Gravity.CENTER);
                GradientDrawable phBg = new GradientDrawable();
                phBg.setColor(Color.parseColor("#DDD5CA"));
                phBg.setCornerRadius(dp(8));
                ph.setBackground(phBg);
                LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(imgSize, imgSize);
                plp.rightMargin = dp(10);
                ph.setLayoutParams(plp);
                TextView phTv = text("이미지\n준비 중", 9, COLOR_INK3, false);
                phTv.setGravity(Gravity.CENTER);
                ph.addView(phTv);
                row.addView(ph);
            }

            LinearLayout textCol = new LinearLayout(this);
            textCol.setOrientation(LinearLayout.VERTICAL);
            textCol.setGravity(Gravity.CENTER_VERTICAL);
            textCol.setLayoutParams(new LinearLayout.LayoutParams(
                    0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

            textCol.addView(text(s[0], 13, COLOR_INK, true));

            TextView descTv = text(s[2], 12, COLOR_INK3, false);
            LinearLayout.LayoutParams dtlp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            dtlp.topMargin = dp(2);
            descTv.setLayoutParams(dtlp);
            textCol.addView(descTv);

            row.addView(textCol);
            box.addView(row);
            count++;
        }
        return box;
    }

    private TextView text(String s, int sizeSp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return t;
    }

    private int dp(int v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP,
                v, getResources().getDisplayMetrics());
    }

    private static String nullSafe(String s) {
        return s == null ? "" : s;
    }

    private static String readStream(InputStream stream) {
        if (stream == null) return "";
        StringBuilder sb = new StringBuilder();
        try (BufferedReader r = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = r.readLine()) != null) sb.append(line).append('\n');
        } catch (Exception ignored) {
        }
        return sb.toString().trim();
    }
}
