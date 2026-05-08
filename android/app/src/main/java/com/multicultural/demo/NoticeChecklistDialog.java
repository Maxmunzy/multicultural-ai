package com.multicultural.demo;

import android.app.Dialog;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.CheckBox;
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
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 한 통신문의 cards/info_cards 체크리스트만 모달로 표시.
 *
 * Step 2 (C) — MainActivity 분석 화면에서 카드 영역 tap 또는 별 버튼으로 진입.
 * 통합 체크리스트(ChecklistActivity)와 별개로 "지금 보고 있는 이 통신문만" 빠르게
 * 체크할 때 사용. Material BottomSheet 의존성 없이 일반 Dialog로 하단 슬라이드 흉내.
 *
 * 사용:
 *   NoticeChecklistDialog.show(activity, baseUrl, parentId, noticeId, cards, infoCards);
 */
public class NoticeChecklistDialog {

    private static final int COLOR_PEACH       = Color.parseColor("#FFD9C2");
    private static final int COLOR_PEACH_DEEP  = Color.parseColor("#FF9D6E");
    private static final int COLOR_PEACH_INK   = Color.parseColor("#B35A2B");
    private static final int COLOR_PAPER       = Color.parseColor("#FFFAF3");
    private static final int COLOR_INK         = Color.parseColor("#2B2018");
    private static final int COLOR_INK2        = Color.parseColor("#5A4A3D");
    private static final int COLOR_INK3        = Color.parseColor("#8A7C70");
    private static final int COLOR_LINE        = Color.parseColor("#EAD9C4");
    private static final int COLOR_MINT_INK    = Color.parseColor("#2F7A55");
    private static final int COLOR_LEMON_INK   = Color.parseColor("#8A6A14");

    private static final ExecutorService executor = Executors.newSingleThreadExecutor();

    private NoticeChecklistDialog() {
    }

    public static void show(
            Context context,
            String baseUrl,
            String parentId,
            String noticeId,
            JSONArray cards,
            JSONArray infoCards
    ) {
        Dialog dialog = new Dialog(context);
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
        dialog.setContentView(buildLayout(context, dialog, baseUrl, parentId, noticeId, cards, infoCards));

        Window window = dialog.getWindow();
        if (window != null) {
            window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
            WindowManager.LayoutParams lp = window.getAttributes();
            lp.gravity = Gravity.BOTTOM;
            lp.width = WindowManager.LayoutParams.MATCH_PARENT;
            lp.height = WindowManager.LayoutParams.WRAP_CONTENT;
            window.setAttributes(lp);
        }
        dialog.show();
    }

    private static View buildLayout(
            Context context,
            Dialog dialog,
            String baseUrl,
            String parentId,
            String noticeId,
            JSONArray cards,
            JSONArray infoCards
    ) {
        LinearLayout root = new LinearLayout(context);
        root.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable rootBg = new GradientDrawable();
        rootBg.setColor(COLOR_PAPER);
        rootBg.setCornerRadii(new float[]{
                dp(context, 20), dp(context, 20),
                dp(context, 20), dp(context, 20),
                0, 0, 0, 0
        });
        root.setBackground(rootBg);
        root.setPadding(0, dp(context, 8), 0, dp(context, 16));

        // grab handle
        View handle = new View(context);
        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(
                dp(context, 40), dp(context, 4));
        hlp.gravity = Gravity.CENTER_HORIZONTAL;
        hlp.bottomMargin = dp(context, 12);
        handle.setLayoutParams(hlp);
        GradientDrawable hbg = new GradientDrawable();
        hbg.setColor(COLOR_LINE);
        hbg.setCornerRadius(dp(context, 999));
        handle.setBackground(hbg);
        root.addView(handle);

        // header
        LinearLayout header = new LinearLayout(context);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(context, 18), 0, dp(context, 18), dp(context, 8));

        TextView title = makeText(context, "📋  이 통신문 체크리스트", 16, COLOR_INK, true);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        title.setLayoutParams(tlp);
        header.addView(title);

        TextView close = makeText(context, "✕", 18, COLOR_INK2, true);
        close.setPadding(dp(context, 8), dp(context, 4), dp(context, 8), dp(context, 4));
        close.setOnClickListener(v -> dialog.dismiss());
        header.addView(close);
        root.addView(header);

        // body — scrollable, max height ~70% screen
        int maxHeight = (int) (context.getResources().getDisplayMetrics().heightPixels * 0.70);
        ScrollView scroll = new ScrollView(context);
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        scroll.setLayoutParams(slp);
        scroll.getLayoutParams().height = maxHeight;
        LinearLayout body = new LinearLayout(context);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(context, 14), dp(context, 4), dp(context, 14), dp(context, 4));
        scroll.addView(body);
        root.addView(scroll);

        int totalCards = appendCards(context, body, baseUrl, parentId, noticeId, "card", cards)
                       + appendCards(context, body, baseUrl, parentId, noticeId, "info", infoCards);
        if (totalCards == 0) {
            TextView empty = makeText(context, "체크할 항목이 없습니다", 14, COLOR_INK3, false);
            empty.setPadding(0, dp(context, 28), 0, dp(context, 28));
            empty.setGravity(Gravity.CENTER);
            body.addView(empty);
        }

        return root;
    }

    private static int appendCards(
            Context context,
            LinearLayout body,
            String baseUrl,
            String parentId,
            String noticeId,
            String cardKind,
            JSONArray cards
    ) {
        if (cards == null) return 0;
        int rendered = 0;
        for (int i = 0; i < cards.length(); i++) {
            JSONObject card = cards.optJSONObject(i);
            if (card == null) continue;
            JSONArray cl = card.optJSONArray("checklist");
            if (cl == null || cl.length() == 0) continue;
            body.addView(buildCardSection(context, baseUrl, parentId, noticeId, cardKind, card, cl));
            rendered++;
        }
        return rendered;
    }

    private static View buildCardSection(
            Context context,
            String baseUrl,
            String parentId,
            String noticeId,
            String cardKind,
            JSONObject card,
            JSONArray cl
    ) {
        LinearLayout section = new LinearLayout(context);
        section.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(context, 14));
        bg.setStroke(dp(context, 1), COLOR_LINE);
        section.setBackground(bg);
        section.setPadding(dp(context, 14), dp(context, 12), dp(context, 14), dp(context, 12));
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        slp.bottomMargin = dp(context, 10);
        section.setLayoutParams(slp);

        String headerKo = card.optString("header_ko", "");
        String dueDate = card.optString("due_date", "");
        TextView head = makeText(context, headerKo, 15, COLOR_INK, true);
        section.addView(head);

        if (!dueDate.isEmpty() && !"null".equals(dueDate)) {
            TextView due = makeText(context, "⌛ " + dueDate, 11, COLOR_PEACH_INK, true);
            due.setPadding(dp(context, 8), dp(context, 3), dp(context, 8), dp(context, 3));
            GradientDrawable dueBg = new GradientDrawable();
            dueBg.setColor(COLOR_PEACH);
            dueBg.setCornerRadius(dp(context, 999));
            due.setBackground(dueBg);
            LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            dlp.topMargin = dp(context, 4);
            due.setLayoutParams(dlp);
            section.addView(due);
        }

        TextView progress = makeText(context, "", 12, COLOR_LEMON_INK, true);
        LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        plp.topMargin = dp(context, 6);
        progress.setLayoutParams(plp);
        section.addView(progress);

        String cardId = card.optString("card_id", "");
        for (int j = 0; j < cl.length(); j++) {
            JSONObject item = cl.optJSONObject(j);
            if (item == null) continue;
            CheckBox cb = new CheckBox(context);
            String label = item.optString("translated", "");
            String ko = item.optString("ko", "");
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
            cblp.topMargin = dp(context, 2);
            cb.setLayoutParams(cblp);

            String itemId = item.optString("item_id", "");
            JSONObject itemRef = item;
            cb.setOnCheckedChangeListener((v, isChecked) -> {
                try { itemRef.put("checked", isChecked); } catch (Exception ignored) {}
                updateProgress(progress, cl);
                toggleItem(context, baseUrl, parentId, noticeId, cardKind, cardId, itemId, isChecked);
            });
            section.addView(cb);
        }
        updateProgress(progress, cl);
        return section;
    }

    private static void updateProgress(TextView progress, JSONArray cl) {
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

    private static void toggleItem(
            Context context,
            String baseUrl,
            String parentId,
            String noticeId,
            String cardKind,
            String cardId,
            String itemId,
            boolean checked
    ) {
        executor.submit(() -> {
            HttpURLConnection conn = null;
            try {
                URL url = new URL(baseUrl + "/notice/checklist/" + noticeId);
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
                    if (context instanceof android.app.Activity) {
                        ((android.app.Activity) context).runOnUiThread(() ->
                                Toast.makeText(context,
                                        "토글 실패 HTTP " + code + ": " + errBody,
                                        Toast.LENGTH_SHORT).show());
                    }
                }
            } catch (Exception ex) {
                final String msg = ex.getMessage() == null ? ex.toString() : ex.getMessage();
                if (context instanceof android.app.Activity) {
                    ((android.app.Activity) context).runOnUiThread(() ->
                            Toast.makeText(context,
                                    "토글 오류: " + msg, Toast.LENGTH_SHORT).show());
                }
            } finally {
                if (conn != null) conn.disconnect();
            }
        });
    }

    private static TextView makeText(Context context, String s, int sizeSp, int color, boolean bold) {
        TextView t = new TextView(context);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return t;
    }

    private static int dp(Context context, int v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP,
                v, context.getResources().getDisplayMetrics());
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
