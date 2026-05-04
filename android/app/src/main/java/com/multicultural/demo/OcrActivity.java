package com.multicultural.demo;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.Typeface;
import android.media.ExifInterface;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;

import com.google.android.gms.tasks.Task;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions;

import org.opencv.android.Utils;
import org.opencv.core.CvType;
import org.opencv.core.Mat;
import org.opencv.core.Size;
import org.opencv.imgproc.CLAHE;
import org.opencv.imgproc.Imgproc;

import android.graphics.Rect;
import org.opencv.core.Core;
import org.opencv.core.MatOfPoint;
import org.opencv.core.MatOfPoint2f;
import org.opencv.core.Point;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
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
import java.util.regex.Pattern;

/**
 * 카메라 사진 → ML Kit Korean OCR → Quality Gate → 백엔드 TXT 업로드
 *
 * 흐름:
 *   1. 카메라 Intent로 원본 사진 촬영 (FileProvider URI)
 *   2. EXIF 회전 보정
 *   3. 전처리 2종 (원본 / grayscale+CLAHE) 병렬 OCR → best 선택 → 표 감지 → 2-pass 재인식
 *   4. Quality Gate: 표 없음 text 0.62 + pattern 0.38 / 표 있음 text 0.50 + pattern 0.35 + table 0.15 ≥ 0.80 → auto_pass
 *   5. pass: 백엔드 /notice/upload → notice_id 반환 → MainActivity
 *      fail: "원문 확인 필요" 경고 + 재촬영 / 그래도 전송 선택
 *
 * 실험 근거 (ocr_lab_schoolbridge Round 5):
 *   ML Kit Korean: 정면 overall 0.82, 기울임 warped_gray CER 0.33, F1 0.93
 *   Tesseract Korean: CER 0.97 → 사용 불가
 */
public class OcrActivity extends Activity {

    // 호출자(MainActivity)가 putExtra로 전달해야 하는 키
    public static final String EXTRA_BASE_URL     = "base_url";
    public static final String EXTRA_TEACHER_ID   = "teacher_id";
    public static final String EXTRA_PARENT_ID    = "parent_id";

    // 결과로 돌려주는 키
    public static final String RESULT_NOTICE_ID   = "notice_id";
    public static final String RESULT_CHAR_COUNT  = "char_count";
    public static final String RESULT_OCR_TEXT    = "ocr_text";

    private static final int REQUEST_CAMERA       = 3001;
    private static final int REQUEST_CAMERA_PERM  = 3002;

    // Quality Gate 임계값 (ocr_lab 실험 결과 기준)
    private static final double AUTO_PASS_THRESHOLD = 0.80;
    private static final int    MIN_TEXT_LENGTH      = 120;

    // Korean/ASCII word char pattern for quality scoring
    private static final Pattern MEANINGFUL = Pattern.compile("[\\uAC00-\\uD7A3A-Za-z0-9]");
    private static final Pattern GARBAGE    = Pattern.compile("[^ \\n\\t\\r\\uAC00-\\uD7A3A-Za-z0-9.,:/()" +
            "\\-_%+~#@&=]");
    private static final Pattern SPACED_CHAR = Pattern.compile("(?:\\S\\s){4,}\\S");

    // 가정통신문 패턴 (pattern_score 계산용)
    private static final Pattern PAT_DATE    = Pattern.compile("\\d{4}[./년]\\s*\\d{1,2}[./월]\\s*\\d{1,2}");
    private static final Pattern PAT_TIME    = Pattern.compile("\\d{1,2}:\\d{2}|오전|오후|AM|PM");
    private static final Pattern PAT_PHONE   = Pattern.compile("0\\d{1,2}[-\\s]?\\d{3,4}[-\\s]?\\d{4}");
    private static final Pattern PAT_AMOUNT  = Pattern.compile("\\d+[,.]?\\d*\\s*원");
    private static final String[] NOTICE_KEYWORDS = {"안내", "신청", "기간", "문의", "대상", "장소", "시간", "참여", "제출"};

    private String baseUrl;
    private String teacherId;
    private String parentId;

    private Uri photoUri;
    private File photoFile;

    private LinearLayout rootLayout;
    private TextView statusText;
    private ProgressBar progressBar;
    private ScrollView resultScroll;
    private TextView resultText;
    private Button retryButton;
    private Button proceedButton;

    private String bestOcrText = "";
    private double bestScore   = 0.0;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private TextRecognizer recognizer;

    // ─────────────────────────────────────────────
    //  Lifecycle
    // ─────────────────────────────────────────────

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        baseUrl   = getIntent().getStringExtra(EXTRA_BASE_URL);
        teacherId = getIntent().getStringExtra(EXTRA_TEACHER_ID);
        parentId  = getIntent().getStringExtra(EXTRA_PARENT_ID);
        if (baseUrl == null) baseUrl = "http://172.30.1.45:8000";

        recognizer = TextRecognition.getClient(new KoreanTextRecognizerOptions.Builder().build());
        buildUI();
        checkCameraPermission();
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        if (recognizer != null) recognizer.close();
        super.onDestroy();
    }

    // ─────────────────────────────────────────────
    //  UI
    // ─────────────────────────────────────────────

    private void buildUI() {
        ScrollView scroll = new ScrollView(this);
        rootLayout = new LinearLayout(this);
        rootLayout.setOrientation(LinearLayout.VERTICAL);
        rootLayout.setPadding(dp(20), dp(24), dp(20), dp(24));
        rootLayout.setBackgroundColor(Color.parseColor("#FFFAF3"));

        TextView title = new TextView(this);
        title.setText("📷  사진 OCR");
        title.setTextSize(20);
        title.setTextColor(Color.parseColor("#2B2018"));
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        title.setPadding(0, 0, 0, dp(4));
        rootLayout.addView(title);

        TextView subtitle = new TextView(this);
        subtitle.setText("가정통신문 사진을 찍으면 AI가 텍스트를 인식합니다.");
        subtitle.setTextSize(13);
        subtitle.setTextColor(Color.parseColor("#8A7C70"));
        subtitle.setPadding(0, 0, 0, dp(20));
        rootLayout.addView(subtitle);

        statusText = new TextView(this);
        statusText.setText("카메라를 준비 중입니다…");
        statusText.setTextSize(14);
        statusText.setTextColor(Color.parseColor("#5A4A3D"));
        statusText.setPadding(0, 0, 0, dp(12));
        rootLayout.addView(statusText);

        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setIndeterminate(true);
        progressBar.setVisibility(android.view.View.GONE);
        LinearLayout.LayoutParams pbp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(4));
        pbp.bottomMargin = dp(16);
        progressBar.setLayoutParams(pbp);
        rootLayout.addView(progressBar);

        resultScroll = new ScrollView(this);
        resultScroll.setVisibility(android.view.View.GONE);
        LinearLayout.LayoutParams rsp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(200));
        rsp.bottomMargin = dp(12);
        resultScroll.setLayoutParams(rsp);
        resultText = new TextView(this);
        resultText.setTextSize(12);
        resultText.setTextColor(Color.parseColor("#2B2018"));
        resultText.setPadding(dp(12), dp(12), dp(12), dp(12));
        resultText.setBackgroundColor(Color.parseColor("#F5EDE0"));
        resultScroll.addView(resultText);
        rootLayout.addView(resultScroll);

        retryButton = makeButton("🔄  다시 촬영", Color.parseColor("#FF9D6E"), Color.WHITE);
        retryButton.setVisibility(android.view.View.GONE);
        retryButton.setOnClickListener(v -> launchCamera());
        rootLayout.addView(retryButton);

        proceedButton = makeButton("📤  그래도 전송", Color.parseColor("#6FCFA1"), Color.WHITE);
        proceedButton.setVisibility(android.view.View.GONE);
        proceedButton.setOnClickListener(v -> uploadOcrText(bestOcrText));
        rootLayout.addView(proceedButton);

        Button cancelButton = makeButton("← 취소", Color.parseColor("#EAD9C4"), Color.parseColor("#5A4A3D"));
        cancelButton.setOnClickListener(v -> finish());
        rootLayout.addView(cancelButton);

        scroll.addView(rootLayout);
        setContentView(scroll);
    }

    private Button makeButton(String label, int bgColor, int textColor) {
        Button btn = new Button(this);
        btn.setText(label);
        btn.setTextColor(textColor);
        btn.setTextSize(14);
        btn.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        btn.setAllCaps(false);
        btn.setBackgroundColor(bgColor);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        p.bottomMargin = dp(10);
        btn.setLayoutParams(p);
        return btn;
    }

    // ─────────────────────────────────────────────
    //  Camera
    // ─────────────────────────────────────────────

    private void checkCameraPermission() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED) {
            launchCamera();
        } else {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.CAMERA}, REQUEST_CAMERA_PERM);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_CAMERA_PERM) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                launchCamera();
            } else {
                Toast.makeText(this, "카메라 권한이 필요합니다.", Toast.LENGTH_LONG).show();
                finish();
            }
        }
    }

    private void launchCamera() {
        try {
            photoFile = File.createTempFile("ocr_", ".jpg",
                    getExternalCacheDir() != null ? getExternalCacheDir() : getCacheDir());
            photoUri = FileProvider.getUriForFile(this,
                    getPackageName() + ".fileprovider", photoFile);
            Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            intent.putExtra(MediaStore.EXTRA_OUTPUT, photoUri);
            startActivityForResult(intent, REQUEST_CAMERA);
        } catch (IOException e) {
            setStatus("❌ 카메라 파일 생성 실패: " + e.getMessage());
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_CAMERA) return;
        if (resultCode != RESULT_OK || photoFile == null || !photoFile.exists()) {
            finish();
            return;
        }
        setStatus("🔍  OCR 분석 중…");
        showProgress(true);
        runOcr();
    }

    // ─────────────────────────────────────────────
    //  OCR Pipeline
    // ─────────────────────────────────────────────

    private void runOcr() {
        executor.execute(() -> {
            Bitmap original = loadAndRotateBitmap(photoFile.getAbsolutePath());
            if (original == null) {
                runOnUiThread(() -> {
                    setStatus("❌ 이미지 로드 실패");
                    showProgress(false);
                });
                return;
            }

            List<Bitmap> variants = buildPreprocessVariants(original);
            // ML Kit는 비동기 API이므로 AtomicInteger로 완료 카운트
            final int[] pending = {variants.size()};
            final String[] texts = new String[variants.size()];
            final double[] scores = new double[variants.size()];

            for (int i = 0; i < variants.size(); i++) {
                final int idx = i;
                InputImage image = InputImage.fromBitmap(variants.get(i), 0);
                Task<Text> task = recognizer.process(image);
                task.addOnSuccessListener(result -> {
                    String text = extractTextFromResult(result);
                    texts[idx] = text;
                    scores[idx] = calculateTextQualityScore(text);
                    synchronized (pending) {
                        pending[0]--;
                        if (pending[0] == 0) onAllVariantsDone(texts, scores);
                    }
                }).addOnFailureListener(e -> {
                    texts[idx] = "";
                    scores[idx] = 0.0;
                    synchronized (pending) {
                        pending[0]--;
                        if (pending[0] == 0) onAllVariantsDone(texts, scores);
                    }
                });
            }
        });
    }

    private void onAllVariantsDone(String[] texts, double[] scores) {
        int bestIdx = 0;
        for (int i = 1; i < scores.length; i++) {
            if (scores[i] > scores[bestIdx]) bestIdx = i;
        }
        bestOcrText = texts[bestIdx] != null ? texts[bestIdx] : "";
        bestScore = scores[bestIdx];

        executor.execute(() -> {
            Bitmap original = loadAndRotateBitmap(photoFile.getAbsolutePath());
            List<Rect> tableRegions = original != null
                    ? detectTableRegions(original) : new ArrayList<>();
            if (!tableRegions.isEmpty() && original != null) {
                runTablePassOcr(original, tableRegions);
            } else {
                finalizeOcr(bestOcrText, bestScore, false);
            }
        });
    }

    private List<Rect> detectTableRegions(Bitmap src) {
        List<Rect> regions = new ArrayList<>();
        try {
            Mat mat = new Mat();
            Utils.bitmapToMat(src, mat);
            Mat gray = new Mat();
            Imgproc.cvtColor(mat, gray, Imgproc.COLOR_RGB2GRAY);

            Mat thresh = new Mat();
            Imgproc.adaptiveThreshold(gray, thresh, 255,
                    Imgproc.ADAPTIVE_THRESH_MEAN_C,
                    Imgproc.THRESH_BINARY_INV, 15, 10);

            int cols = gray.cols();
            int rows = gray.rows();
            Mat hKernel = Imgproc.getStructuringElement(Imgproc.MORPH_RECT, new Size(cols / 8, 1));
            Mat hLines = new Mat();
            Imgproc.erode(thresh, hLines, hKernel);
            Imgproc.dilate(hLines, hLines, hKernel);

            Mat vKernel = Imgproc.getStructuringElement(Imgproc.MORPH_RECT, new Size(1, rows / 8));
            Mat vLines = new Mat();
            Imgproc.erode(thresh, vLines, vKernel);
            Imgproc.dilate(vLines, vLines, vKernel);

            Mat combined = new Mat();
            Core.add(hLines, vLines, combined);
            Mat dilKernel = Imgproc.getStructuringElement(Imgproc.MORPH_RECT, new Size(5, 5));
            Imgproc.dilate(combined, combined, dilKernel);

            List<MatOfPoint> contours = new ArrayList<>();
            Imgproc.findContours(combined, contours, new Mat(),
                    Imgproc.RETR_EXTERNAL, Imgproc.CHAIN_APPROX_SIMPLE);

            double minArea = (double) src.getWidth() * src.getHeight() / 50.0;
            for (MatOfPoint contour : contours) {
                org.opencv.core.Rect r = Imgproc.boundingRect(contour);
                if (r.area() >= minArea) {
                    int pad = 8;
                    int x = Math.max(0, r.x - pad);
                    int y = Math.max(0, r.y - pad);
                    int w = Math.min(src.getWidth() - x, r.width + pad * 2);
                    int h = Math.min(src.getHeight() - y, r.height + pad * 2);
                    regions.add(new Rect(x, y, x + w, y + h));
                }
            }
        } catch (Exception e) {
            // fall through, return empty
        }
        return regions;
    }

    private void runTablePassOcr(Bitmap original, List<Rect> regions) {
        final int total = regions.size();
        final int[] pending = {total};
        final String[] tableParts = new String[total];

        for (int i = 0; i < total; i++) {
            final int idx = i;
            Rect r = regions.get(i);
            try {
                Bitmap crop = Bitmap.createBitmap(original, r.left, r.top, r.width(), r.height());
                Bitmap proc = toGrayscaleClahe(crop);
                InputImage img = InputImage.fromBitmap(proc != null ? proc : crop, 0);
                recognizer.process(img)
                        .addOnSuccessListener(result -> {
                            tableParts[idx] = extractTextFromResult(result);
                            synchronized (pending) {
                                if (--pending[0] == 0) mergeAndFinalize(tableParts);
                            }
                        })
                        .addOnFailureListener(e -> {
                            tableParts[idx] = "";
                            synchronized (pending) {
                                if (--pending[0] == 0) mergeAndFinalize(tableParts);
                            }
                        });
            } catch (Exception e) {
                tableParts[idx] = "";
                synchronized (pending) {
                    if (--pending[0] == 0) mergeAndFinalize(tableParts);
                }
            }
        }
    }

    private void mergeAndFinalize(String[] tableParts) {
        StringBuilder sb = new StringBuilder(bestOcrText);
        boolean hasTableText = false;
        for (String part : tableParts) {
            if (part != null && !part.isEmpty()) {
                sb.append("\n").append(part);
                hasTableText = true;
            }
        }
        finalizeOcr(sb.toString(), bestScore, hasTableText);
    }

    private void finalizeOcr(String text, double textScore, boolean hasTable) {
        bestOcrText = text;
        double patternScore = calculatePatternScore(text);
        double overall = hasTable
                ? textScore * 0.50 + patternScore * 0.35 + calculateTextQualityScore(text) * 0.15
                : textScore * 0.62 + patternScore * 0.38;

        final double finalOverall = overall;
        runOnUiThread(() -> {
            showProgress(false);
            if (bestOcrText.trim().isEmpty()) {
                setStatus("❌ 텍스트를 인식하지 못했습니다. 다시 촬영해 주세요.");
                showRetry(false);
                return;
            }
            if (finalOverall >= AUTO_PASS_THRESHOLD) {
                setStatus(String.format("✅ OCR 완료 (점수 %.2f) — 업로드 중…", finalOverall));
                uploadOcrText(bestOcrText);
            } else {
                showQualityWarning(bestOcrText, finalOverall);
            }
        });
    }

    private List<Bitmap> buildPreprocessVariants(Bitmap src) {
        List<Bitmap> variants = new ArrayList<>();
        variants.add(src);

        Bitmap gray = toGrayscaleClahe(src);
        if (gray != null) variants.add(gray);

        Bitmap warped = warpDocument(src);
        if (warped != null) {
            variants.add(warped);
            Bitmap warpedGray = toGrayscaleClahe(warped);
            if (warpedGray != null) variants.add(warpedGray);
        }

        return variants;
    }

    private Bitmap warpDocument(Bitmap src) {
        try {
            Mat mat = new Mat();
            Utils.bitmapToMat(src, mat);
            Mat gray = new Mat();
            Imgproc.cvtColor(mat, gray, Imgproc.COLOR_RGB2GRAY);

            Mat blurred = new Mat();
            Imgproc.GaussianBlur(gray, blurred, new Size(5, 5), 0);
            Mat edges = new Mat();
            Imgproc.Canny(blurred, edges, 75, 200);
            Mat dilKernel = Imgproc.getStructuringElement(Imgproc.MORPH_RECT, new Size(3, 3));
            Imgproc.dilate(edges, edges, dilKernel);

            List<MatOfPoint> contours = new ArrayList<>();
            Imgproc.findContours(edges, contours, new Mat(),
                    Imgproc.RETR_LIST, Imgproc.CHAIN_APPROX_SIMPLE);

            MatOfPoint2f docContour = null;
            double maxArea = src.getWidth() * src.getHeight() * 0.2;
            for (MatOfPoint contour : contours) {
                MatOfPoint2f c2f = new MatOfPoint2f(contour.toArray());
                double peri = Imgproc.arcLength(c2f, true);
                MatOfPoint2f approx = new MatOfPoint2f();
                Imgproc.approxPolyDP(c2f, approx, 0.02 * peri, true);
                if (approx.total() == 4) {
                    double area = Imgproc.contourArea(approx);
                    if (area > maxArea) {
                        maxArea = area;
                        docContour = approx;
                    }
                }
            }
            if (docContour == null) return null;

            Point[] ordered = orderPoints(docContour.toArray());
            double w = Math.max(
                    Math.hypot(ordered[2].x - ordered[3].x, ordered[2].y - ordered[3].y),
                    Math.hypot(ordered[1].x - ordered[0].x, ordered[1].y - ordered[0].y));
            double h = Math.max(
                    Math.hypot(ordered[1].x - ordered[2].x, ordered[1].y - ordered[2].y),
                    Math.hypot(ordered[0].x - ordered[3].x, ordered[0].y - ordered[3].y));

            MatOfPoint2f dst = new MatOfPoint2f(
                    new Point(0, 0), new Point(w - 1, 0),
                    new Point(w - 1, h - 1), new Point(0, h - 1));
            Mat M = Imgproc.getPerspectiveTransform(new MatOfPoint2f(ordered), dst);
            Mat result = new Mat();
            Imgproc.warpPerspective(mat, result, M, new Size(w, h));

            Bitmap bmp = Bitmap.createBitmap(result.cols(), result.rows(), Bitmap.Config.ARGB_8888);
            Utils.matToBitmap(result, bmp);
            return bmp;
        } catch (Exception e) {
            return null;
        }
    }

    private Point[] orderPoints(Point[] pts) {
        Point tl = pts[0], tr = pts[0], br = pts[0], bl = pts[0];
        double minSum = Double.MAX_VALUE, maxSum = -Double.MAX_VALUE;
        double minDiff = Double.MAX_VALUE, maxDiff = -Double.MAX_VALUE;
        for (Point p : pts) {
            double sum = p.x + p.y, diff = p.y - p.x;
            if (sum < minSum) { minSum = sum; tl = p; }
            if (sum > maxSum) { maxSum = sum; br = p; }
            if (diff < minDiff) { minDiff = diff; tr = p; }
            if (diff > maxDiff) { maxDiff = diff; bl = p; }
        }
        return new Point[]{tl, tr, br, bl};
    }

    private Bitmap toGrayscaleClahe(Bitmap src) {
        try {
            Mat mat = new Mat();
            Utils.bitmapToMat(src, mat);
            Mat gray = new Mat();
            Imgproc.cvtColor(mat, gray, Imgproc.COLOR_RGB2GRAY);
            CLAHE clahe = Imgproc.createCLAHE(2.0, new Size(8, 8));
            Mat enhanced = new Mat();
            clahe.apply(gray, enhanced);
            // ML Kit는 RGB를 기대하므로 다시 3채널로
            Mat rgb = new Mat();
            Imgproc.cvtColor(enhanced, rgb, Imgproc.COLOR_GRAY2RGB);
            Bitmap result = Bitmap.createBitmap(rgb.cols(), rgb.rows(), Bitmap.Config.ARGB_8888);
            Utils.matToBitmap(rgb, result);
            return result;
        } catch (Exception e) {
            return null;
        }
    }

    private String extractTextFromResult(Text result) {
        StringBuilder sb = new StringBuilder();
        for (Text.TextBlock block : result.getTextBlocks()) {
            sb.append(block.getText()).append("\n");
        }
        return sb.toString().trim();
    }

    // ─────────────────────────────────────────────
    //  Quality Gate (Python ocr_quality_gate.py 포팅)
    // ─────────────────────────────────────────────

    private double calculateTextQualityScore(String text) {
        if (text == null || text.trim().length() < MIN_TEXT_LENGTH) return 0.0;

        int totalChars = Math.max(text.length(), 1);
        int meaningfulChars = countMatches(MEANINGFUL, text);
        int garbageChars    = countMatches(GARBAGE, text);
        int spacedChars     = countSpacedChar(text);

        String[] lines = text.split("\\n");
        int lineCount   = Math.max(lines.length, 1);
        int shortCount  = 0;
        int dupCount    = 0;
        int garbLineCount = 0;
        java.util.Set<String> seen = new java.util.HashSet<>();

        for (String line : lines) {
            String compact = line.trim().replaceAll("\\s+", "");
            if (compact.length() <= 3) shortCount++;
            if (!compact.isEmpty()) {
                if (seen.contains(compact)) dupCount++;
                else seen.add(compact);
            }
            int mInLine = countMatches(MEANINGFUL, line);
            if (line.trim().length() >= 8 &&
                    (double) mInLine / Math.max(line.length(), 1) < 0.35) {
                garbLineCount++;
            }
        }

        double meaningfulRatio  = (double) meaningfulChars / totalChars;
        double garbageRatio     = (double) garbageChars    / totalChars;
        double shortLineRatio   = (double) shortCount      / lineCount;
        double dupLineRatio     = (double) dupCount        / lineCount;
        double spacedCharRatio  = (double) spacedChars     / totalChars;
        double garbLineRatio    = (double) garbLineCount   / lineCount;

        double penalty = garbageRatio * 1.7
                + shortLineRatio  * 0.18
                + dupLineRatio    * 0.25
                + spacedCharRatio * 0.45
                + garbLineRatio   * 0.35;

        double score = clamp(meaningfulRatio * 1.05 - penalty);
        if (garbageRatio > 0.10) score = Math.min(score, 0.80);
        if (shortLineRatio > 0.35) score = Math.min(score, 0.80);
        return score;
    }

    private double calculatePatternScore(String text) {
        if (text == null || text.isEmpty()) return 0.0;
        int core = 0;
        if (PAT_DATE.matcher(text).find())   core++;
        if (PAT_TIME.matcher(text).find())   core++;
        if (PAT_PHONE.matcher(text).find())  core++;
        if (PAT_AMOUNT.matcher(text).find()) core++;
        double score = Math.min(core / 5.0, 1.0) * 0.72;

        int kwHits = 0;
        for (String kw : NOTICE_KEYWORDS) {
            if (text.contains(kw)) kwHits++;
        }
        score += Math.min(kwHits / 5.0, 1.0) * 0.28;
        return clamp(score);
    }

    private int countMatches(Pattern p, String text) {
        java.util.regex.Matcher m = p.matcher(text);
        int count = 0;
        while (m.find()) count++;
        return count;
    }

    private int countSpacedChar(String text) {
        return countMatches(SPACED_CHAR, text);
    }

    private double clamp(double v) {
        return Math.max(0.0, Math.min(1.0, v));
    }

    // ─────────────────────────────────────────────
    //  Upload
    // ─────────────────────────────────────────────

    private void uploadOcrText(String ocrText) {
        showProgress(true);
        setStatus("📤  백엔드 업로드 중…");

        executor.execute(() -> {
            String filename = "ocr_result.txt";
            byte[] bytes = ocrText.getBytes(StandardCharsets.UTF_8);
            String boundary = "----OcrBoundary" + System.currentTimeMillis();
            HttpURLConnection conn = null;
            String noticeId = "";
            int charCount = 0;
            String errorMsg = "";

            try {
                URL url = new URL(baseUrl + "/notice/upload-self");
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setConnectTimeout(10000);
                conn.setReadTimeout(180000);
                conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
                conn.setRequestProperty("Accept", "application/json");
                if (parentId != null && !parentId.isEmpty()) {
                    conn.setRequestProperty("X-User-Id", parentId);
                }
                conn.setDoOutput(true);

                try (OutputStream os = conn.getOutputStream()) {
                    writeField(os, boundary, "parent_id", parentId != null ? parentId : "parent_001");
                    writeFilePart(os, boundary, "file", filename, bytes);
                    os.write(("--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
                }

                int code = conn.getResponseCode();
                InputStream is = code >= 200 && code < 300
                        ? conn.getInputStream() : conn.getErrorStream();
                String body = readStream(is);

                if (code < 200 || code >= 300) {
                    errorMsg = "HTTP " + code + ": " + body;
                } else {
                    org.json.JSONObject json = new org.json.JSONObject(body);
                    org.json.JSONObject d = json.optJSONObject("data");
                    noticeId  = d != null ? d.optString("notice_id", "") : "";
                    charCount = d != null ? d.optInt("char_count", 0) : 0;
                }
            } catch (Exception e) {
                errorMsg = e.getMessage() != null ? e.getMessage() : e.toString();
            } finally {
                if (conn != null) conn.disconnect();
            }

            final String fNoticeId  = noticeId;
            final int    fCharCount = charCount;
            final String fError     = errorMsg;

            runOnUiThread(() -> {
                showProgress(false);
                if (!fError.isEmpty()) {
                    setStatus("❌ 업로드 실패: " + fError);
                    showRetry(true);
                } else {
                    Intent result = new Intent();
                    result.putExtra(RESULT_NOTICE_ID,  fNoticeId);
                    result.putExtra(RESULT_CHAR_COUNT, fCharCount);
                    result.putExtra(RESULT_OCR_TEXT,   ocrText);
                    setResult(RESULT_OK, result);
                    finish();
                }
            });
        });
    }

    // ─────────────────────────────────────────────
    //  Quality Warning Dialog
    // ─────────────────────────────────────────────

    private void showQualityWarning(String text, double score) {
        setStatus(String.format("⚠️  OCR 품질 낮음 (점수 %.2f / 기준 %.2f)", score, AUTO_PASS_THRESHOLD));
        resultText.setText(text.length() > 500 ? text.substring(0, 500) + "…" : text);
        resultScroll.setVisibility(android.view.View.VISIBLE);
        showRetry(true);
    }

    // ─────────────────────────────────────────────
    //  Image helpers
    // ─────────────────────────────────────────────

    private Bitmap loadAndRotateBitmap(String path) {
        try {
            Bitmap bmp = BitmapFactory.decodeFile(path);
            if (bmp == null) return null;
            ExifInterface exif = new ExifInterface(path);
            int orientation = exif.getAttributeInt(
                    ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL);
            Matrix matrix = new Matrix();
            switch (orientation) {
                case ExifInterface.ORIENTATION_ROTATE_90:  matrix.postRotate(90);  break;
                case ExifInterface.ORIENTATION_ROTATE_180: matrix.postRotate(180); break;
                case ExifInterface.ORIENTATION_ROTATE_270: matrix.postRotate(270); break;
            }
            return Bitmap.createBitmap(bmp, 0, 0, bmp.getWidth(), bmp.getHeight(), matrix, true);
        } catch (Exception e) {
            return null;
        }
    }

    // ─────────────────────────────────────────────
    //  Multipart helpers
    // ─────────────────────────────────────────────

    private void writeField(OutputStream os, String boundary,
                            String name, String value) throws IOException {
        String part = "--" + boundary + "\r\n"
                + "Content-Disposition: form-data; name=\"" + name + "\"\r\n\r\n"
                + value + "\r\n";
        os.write(part.getBytes(StandardCharsets.UTF_8));
    }

    private void writeFilePart(OutputStream os, String boundary,
                               String fieldName, String filename,
                               byte[] data) throws IOException {
        String header = "--" + boundary + "\r\n"
                + "Content-Disposition: form-data; name=\"" + fieldName
                + "\"; filename=\"" + filename + "\"\r\n"
                + "Content-Type: text/plain; charset=utf-8\r\n\r\n";
        os.write(header.getBytes(StandardCharsets.UTF_8));
        os.write(data);
        os.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }

    private String readStream(InputStream stream) throws Exception {
        if (stream == null) return "";
        StringBuilder sb = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) sb.append(line).append('\n');
        }
        return sb.toString().trim();
    }

    // ─────────────────────────────────────────────
    //  UI helpers
    // ─────────────────────────────────────────────

    private void setStatus(String msg) {
        if (statusText != null) statusText.setText(msg);
    }

    private void showProgress(boolean show) {
        if (progressBar != null)
            progressBar.setVisibility(show ? android.view.View.VISIBLE : android.view.View.GONE);
    }

    private void showRetry(boolean showProceed) {
        if (retryButton != null) retryButton.setVisibility(android.view.View.VISIBLE);
        if (proceedButton != null)
            proceedButton.setVisibility(showProceed && !bestOcrText.isEmpty()
                    ? android.view.View.VISIBLE : android.view.View.GONE);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
