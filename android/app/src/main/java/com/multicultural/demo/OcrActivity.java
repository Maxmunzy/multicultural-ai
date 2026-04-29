package com.multicultural.demo;

import android.Manifest;
import android.app.Activity;
import android.util.Log;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ColorMatrix;
import android.graphics.ColorMatrixColorFilter;
import android.graphics.Paint;
import android.graphics.pdf.PdfRenderer;

import org.opencv.android.OpenCVLoader;
import org.opencv.android.Utils;
import org.opencv.core.Mat;
import org.opencv.core.MatOfPoint;
import org.opencv.core.MatOfPoint2f;
import org.opencv.core.Point;
import org.opencv.core.Size;
import org.opencv.imgproc.Imgproc;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.provider.MediaStore;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

public class OcrActivity extends Activity {

    private static final int REQ_PDF    = 1;
    private static final int REQ_CAMERA = 2;
    private static final int REQ_CAMERA_PERMISSION = 3;

    private ImageView ivPreview;
    private EditText  etResult;
    private TextView  tvStatus;
    private Uri       cameraImageUri;
    private Bitmap    currentBitmap;
    private TextRecognizer recognizer;

    // 멀티 variant 자동 선택용
    private final Map<String, String> variantResults = new LinkedHashMap<>();
    private AtomicInteger pendingVariants = new AtomicInteger(0);
    private String currentBaseLabel = "";

    private static final int[] COND_EXPERIMENT = {2, 3, 4};
    private static final String[] COND_LABELS  = {"정면 촬영", "기울임 촬영", "구겨짐 촬영"};
    private int selectedCond = 0;   // 0=정면, 1=기울임, 2=구겨짐
    private android.widget.Button[] condBtns;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_ocr);

        recognizer = TextRecognition.getClient(
                new KoreanTextRecognizerOptions.Builder().build()
        );

        ivPreview = findViewById(R.id.ivPreview);
        etResult  = findViewById(R.id.etResult);
        tvStatus  = findViewById(R.id.tvStatus);

        // 실험1: PDF 파일 피커
        findViewById(R.id.btnGallery).setOnClickListener(v -> {
            Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
            intent.setType("application/pdf");
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            startActivityForResult(Intent.createChooser(intent, "PDF 선택"), REQ_PDF);
        });

        // 카메라 조건 선택 버튼
        condBtns = new android.widget.Button[]{
                (android.widget.Button) findViewById(R.id.btnCond1),
                (android.widget.Button) findViewById(R.id.btnCond2),
                (android.widget.Button) findViewById(R.id.btnCond3)
        };
        for (int i = 0; i < condBtns.length; i++) {
            final int idx = i;
            condBtns[i].setOnClickListener(v -> selectCondition(idx));
        }
        selectCondition(0);   // 기본값: 정면

        // 실험2~4: 카메라 직접 촬영
        findViewById(R.id.btnCamera).setOnClickListener(v -> {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA_PERMISSION);
            } else {
                launchCamera();
            }
        });

        // 텍스트 복사
        findViewById(R.id.btnCopy).setOnClickListener(v -> {
            String text = etResult.getText().toString();
            if (text.isEmpty()) return;
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("ocr_result", text));
            Toast.makeText(this, "복사됨", Toast.LENGTH_SHORT).show();
        });

        // 이미지 저장
        findViewById(R.id.btnSave).setOnClickListener(v -> saveCurrentImage());
    }

    private void selectCondition(int idx) {
        selectedCond = idx;
        int[] colors = {0xFF2196F3, 0xFFAAAAAA, 0xFFAAAAAA};
        colors[idx] = 0xFFFF5722;
        for (int i = 0; i < condBtns.length; i++) {
            condBtns[i].setBackgroundTintList(
                    android.content.res.ColorStateList.valueOf(colors[i]));
        }
    }

    private void launchCamera() {
        File imageFile = new File(getCacheDir(), "images/ocr_" + System.currentTimeMillis() + ".jpg");
        if (imageFile.getParentFile() != null) imageFile.getParentFile().mkdirs();
        cameraImageUri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", imageFile);
        Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
        intent.putExtra(MediaStore.EXTRA_OUTPUT, cameraImageUri);
        startActivityForResult(intent, REQ_CAMERA);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK) return;

        if (requestCode == REQ_PDF && data != null && data.getData() != null) {
            runOcrFromPdf(data.getData());
        } else if (requestCode == REQ_CAMERA) {
            loadBitmapFromUri(cameraImageUri);
            if (currentBitmap != null) {
                currentBaseLabel = "실험" + COND_EXPERIMENT[selectedCond] + "_" + COND_LABELS[selectedCond];
                variantResults.clear();
                pendingVariants.set(6);
                tvStatus.setText("6종 전처리 OCR 실행 중...");
                etResult.setText("");
                Bitmap warped = preprocessPerspective(currentBitmap);
                ivPreview.setImageBitmap(warped);
                runVariantOcr(currentBitmap,                    "raw");
                runVariantOcr(preprocessForOcr(currentBitmap),  "gray_contrast");
                runVariantOcr(preprocessBinary(currentBitmap),   "binary");
                runVariantOcr(warped,                            "warped");
                runVariantOcr(preprocessForOcr(warped),          "warped_gray");
                runVariantOcr(preprocessBinary(warped),          "warped_binary");
            }
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        if (requestCode == REQ_CAMERA_PERMISSION
                && grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            launchCamera();
        } else {
            Toast.makeText(this, "카메라 권한이 필요합니다", Toast.LENGTH_SHORT).show();
        }
    }

    // 카메라 URI → EXIF 회전 보정 → currentBitmap 로드
    private void loadBitmapFromUri(Uri uri) {
        try {
            InputStream is = getContentResolver().openInputStream(uri);
            Bitmap raw = BitmapFactory.decodeStream(is);
            if (is != null) is.close();

            // EXIF 회전 읽어서 보정
            InputStream exifIs = getContentResolver().openInputStream(uri);
            androidx.exifinterface.media.ExifInterface exif =
                    new androidx.exifinterface.media.ExifInterface(exifIs);
            if (exifIs != null) exifIs.close();

            int orientation = exif.getAttributeInt(
                    androidx.exifinterface.media.ExifInterface.TAG_ORIENTATION,
                    androidx.exifinterface.media.ExifInterface.ORIENTATION_NORMAL);
            int degrees = 0;
            if (orientation == androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_90)  degrees = 90;
            else if (orientation == androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_180) degrees = 180;
            else if (orientation == androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_270) degrees = 270;

            if (degrees != 0 && raw != null) {
                android.graphics.Matrix matrix = new android.graphics.Matrix();
                matrix.postRotate(degrees);
                currentBitmap = Bitmap.createBitmap(raw, 0, 0, raw.getWidth(), raw.getHeight(), matrix, true);
                raw.recycle();
            } else {
                currentBitmap = raw;
            }
        } catch (IOException e) {
            currentBitmap = null;
        }
    }

    // PDF → 1페이지 Bitmap → OCR
    private void runOcrFromPdf(Uri pdfUri) {
        tvStatus.setText("실험1 (PDF) — 렌더링 중...");
        etResult.setText("");

        new Thread(() -> {
            try {
                ParcelFileDescriptor pfd = getContentResolver().openFileDescriptor(pdfUri, "r");
                if (pfd == null) throw new IOException("PDF 열기 실패");

                PdfRenderer renderer = new PdfRenderer(pfd);
                PdfRenderer.Page page = renderer.openPage(0);

                int width  = page.getWidth()  * 2;
                int height = page.getHeight() * 2;
                Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
                Canvas canvas = new Canvas(bitmap);
                canvas.drawColor(Color.WHITE);
                page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
                page.close();
                renderer.close();
                pfd.close();

                runOnUiThread(() -> {
                    currentBitmap = bitmap;
                    ivPreview.setImageBitmap(bitmap);
                    runOcrFromBitmap(bitmap, "실험1 (PDF 1페이지)");
                });

            } catch (IOException e) {
                runOnUiThread(() -> tvStatus.setText("PDF 렌더링 실패: " + e.getMessage()));
            }
        }).start();
    }

    private void runOcrFromImage(Uri uri, String label) {
        tvStatus.setText(label + " — 인식 중...");
        ivPreview.setImageURI(uri);
        etResult.setText("");
        try {
            InputImage image = InputImage.fromFilePath(this, uri);
            runOcrOnInputImage(image, label);
        } catch (IOException e) {
            tvStatus.setText("이미지 로드 실패: " + e.getMessage());
        }
    }

    private void runOcrFromBitmap(Bitmap bitmap, String label) {
        tvStatus.setText(label + " — OCR 인식 중...");
        InputImage image = InputImage.fromBitmap(bitmap, 0);
        runOcrOnInputImage(image, label);
    }

    private void runOcrOnInputImage(InputImage image, String label) {
        recognizer.process(image)
                .addOnSuccessListener(result -> {
                    String cleaned = postProcess(result.getText());
                    etResult.setText(cleaned);
                    tvStatus.setText(label + " — 완료 (" + result.getTextBlocks().size() + " 블록)");
                    Log.d("OCR_RESULT", "=== " + label + " ===\n" + cleaned);
                    autoSaveText(cleaned, label);
                })
                .addOnFailureListener(e ->
                        tvStatus.setText(label + " — 실패: " + e.getMessage())
                );
    }

    // OCR 결과 텍스트 자동 저장 (OCR 완료 시 호출)
    private void autoSaveText(String text, String label) {
        String timestamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.KOREA).format(new Date());
        String filename  = "OCR_RESULT_" + timestamp + ".txt";
        String content   = "[" + label + "]\n" + timestamp + "\n\n" + text;

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentValues values = new ContentValues();
                values.put(MediaStore.Downloads.DISPLAY_NAME, filename);
                values.put(MediaStore.Downloads.MIME_TYPE, "text/plain");
                values.put(MediaStore.Downloads.RELATIVE_PATH, "Download/OCR_TEST");
                Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                if (uri != null) {
                    try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                        if (out != null) {
                            out.write(new byte[]{(byte)0xEF, (byte)0xBB, (byte)0xBF}); // UTF-8 BOM
                            out.write(content.getBytes("UTF-8"));
                        }
                    }
                }
            } else {
                File dir = new File(getExternalFilesDir(null), "OCR_TEST");
                dir.mkdirs();
                File file = new File(dir, filename);
                try (OutputStream out = new java.io.FileOutputStream(file)) {
                    out.write(new byte[]{(byte)0xEF, (byte)0xBB, (byte)0xBF}); // UTF-8 BOM
                    out.write(content.getBytes("UTF-8"));
                }
            }
            Log.d("OCR_RESULT", "텍스트 자동 저장: Download/OCR_TEST/" + filename);
        } catch (Exception e) {
            Log.e("OCR_RESULT", "텍스트 저장 실패: " + e.getMessage());
        }
    }

    // 현재 이미지를 갤러리에 저장
    private void saveCurrentImage() {
        if (currentBitmap == null) {
            Toast.makeText(this, "저장할 이미지가 없습니다", Toast.LENGTH_SHORT).show();
            return;
        }
        String timestamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.KOREA).format(new Date());
        String filename  = "OCR_TEST_" + timestamp + ".jpg";

        try {
            Uri savedUri;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentValues values = new ContentValues();
                values.put(MediaStore.Images.Media.DISPLAY_NAME, filename);
                values.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
                values.put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/OCR_TEST");
                savedUri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
                if (savedUri == null) throw new IOException("MediaStore insert 실패");
                try (OutputStream out = getContentResolver().openOutputStream(savedUri)) {
                    currentBitmap.compress(Bitmap.CompressFormat.JPEG, 95, out);
                }
            } else {
                // API 28 이하
                String saved = MediaStore.Images.Media.insertImage(
                        getContentResolver(), currentBitmap, filename, "OCR 테스트 이미지");
                if (saved == null) throw new IOException("저장 실패");
            }
            Toast.makeText(this, "갤러리에 저장됨: " + filename, Toast.LENGTH_LONG).show();
        } catch (IOException e) {
            Toast.makeText(this, "저장 실패: " + e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }

    // variant OCR 실행 → 결과 수집 → 전부 완료 시 자동 선택
    private void runVariantOcr(Bitmap bitmap, String variantName) {
        String label = currentBaseLabel + "_" + variantName;
        InputImage image = InputImage.fromBitmap(bitmap, 0);
        recognizer.process(image)
                .addOnSuccessListener(result -> {
                    String cleaned = postProcess(result.getText());
                    autoSaveText(cleaned, label);
                    synchronized (variantResults) {
                        variantResults.put(variantName, cleaned);
                    }
                    if (pendingVariants.decrementAndGet() == 0) {
                        runOnUiThread(this::selectBestVariant);
                    }
                })
                .addOnFailureListener(e -> {
                    synchronized (variantResults) {
                        variantResults.put(variantName, "");
                    }
                    if (pendingVariants.decrementAndGet() == 0) {
                        runOnUiThread(this::selectBestVariant);
                    }
                });
    }

    private void selectBestVariant() {
        String bestVariant = null;
        double bestScore = -1;
        synchronized (variantResults) {
            for (Map.Entry<String, String> entry : variantResults.entrySet()) {
                double score = scoreText(entry.getValue());
                if (score > bestScore) {
                    bestScore = score;
                    bestVariant = entry.getKey();
                }
            }
        }
        String bestText = variantResults.getOrDefault(bestVariant, "");
        etResult.setText(bestText);
        tvStatus.setText("완료 — best: " + bestVariant + " (" + String.format("%.3f", bestScore) + ")");
        autoSaveText(bestText, currentBaseLabel + "_BEST");
        Log.d("OCR_BEST", "selected=" + bestVariant + " score=" + bestScore);
    }

    // 텍스트 품질 점수 (Quality Gate 간소화 버전)
    private double scoreText(String text) {
        if (text == null || text.length() < 50) return 0.0;
        int total = Math.max(text.length(), 1);
        int meaningful = 0, garbage = 0, shortLines = 0, dupLines = 0;
        java.util.Set<String> seen = new java.util.HashSet<>();
        for (char c : text.toCharArray()) {
            if ((c >= '가' && c <= '힣') || Character.isLetterOrDigit(c)) meaningful++;
            else if (c != ' ' && c != '\n' && c != '\t' && c != '\r' && c != '.' && c != ',' && c != ':' && c != '/' && c != '(' && c != ')' && c != '-') garbage++;
        }
        for (String line : text.split("\n")) {
            String t = line.trim().replaceAll("\\s+", "");
            if (t.length() <= 3) shortLines++;
            if (!t.isEmpty() && !seen.add(t)) dupLines++;
        }
        int lineCount = Math.max(text.split("\n").length, 1);
        double meaningfulRatio = (double) meaningful / total;
        double penalty = (double) garbage / total * 1.7
                + (double) shortLines / lineCount * 0.18
                + (double) dupLines / lineCount * 0.25;
        return Math.max(0, Math.min(1, meaningfulRatio * 1.05 - penalty));
    }

    // Perspective transform — 문서 사각형 감지 후 왜곡 보정
    private Bitmap preprocessPerspective(Bitmap src) {
        if (!OpenCVLoader.initLocal()) return src.copy(src.getConfig(), false);

        Mat mat = new Mat();
        Utils.bitmapToMat(src, mat);

        Mat gray = new Mat();
        Imgproc.cvtColor(mat, gray, Imgproc.COLOR_RGBA2GRAY);
        Imgproc.GaussianBlur(gray, gray, new Size(5, 5), 0);

        Mat edges = new Mat();
        Imgproc.Canny(gray, edges, 60, 180);

        java.util.List<MatOfPoint> contours = new java.util.ArrayList<>();
        Imgproc.findContours(edges, contours, new Mat(), Imgproc.RETR_LIST, Imgproc.CHAIN_APPROX_SIMPLE);
        contours.sort((a, b) -> Double.compare(Imgproc.contourArea(b), Imgproc.contourArea(a)));

        double imageArea = mat.rows() * mat.cols();
        MatOfPoint2f docQuad = null;

        for (MatOfPoint contour : contours.subList(0, Math.min(10, contours.size()))) {
            MatOfPoint2f c2f = new MatOfPoint2f(contour.toArray());
            double perimeter = Imgproc.arcLength(c2f, true);
            MatOfPoint2f approx = new MatOfPoint2f();
            Imgproc.approxPolyDP(c2f, approx, 0.02 * perimeter, true);
            if (approx.total() == 4 && Imgproc.contourArea(approx) > imageArea * 0.15) {
                docQuad = approx;
                break;
            }
        }

        if (docQuad == null) return src.copy(src.getConfig(), false);

        // 4점 정렬 후 warpPerspective
        Point[] pts = docQuad.toArray();
        pts = orderPoints(pts);
        double widthA = dist(pts[2], pts[3]), widthB = dist(pts[1], pts[0]);
        double heightA = dist(pts[1], pts[2]), heightB = dist(pts[0], pts[3]);
        int maxW = (int) Math.max(widthA, widthB);
        int maxH = (int) Math.max(heightA, heightB);

        MatOfPoint2f src4 = new MatOfPoint2f(pts[0], pts[1], pts[2], pts[3]);
        MatOfPoint2f dst4 = new MatOfPoint2f(
                new Point(0, 0), new Point(maxW - 1, 0),
                new Point(maxW - 1, maxH - 1), new Point(0, maxH - 1));

        Mat M = Imgproc.getPerspectiveTransform(src4, dst4);
        Mat warped = new Mat();
        Imgproc.warpPerspective(mat, warped, M, new Size(maxW, maxH));

        Bitmap result = Bitmap.createBitmap(maxW, maxH, Bitmap.Config.ARGB_8888);
        Utils.matToBitmap(warped, result);
        return result;
    }

    private double dist(Point a, Point b) {
        return Math.sqrt(Math.pow(a.x - b.x, 2) + Math.pow(a.y - b.y, 2));
    }

    private Point[] orderPoints(Point[] pts) {
        // top-left, top-right, bottom-right, bottom-left 순서로 정렬
        Point[] rect = new Point[4];
        double[] s = new double[4], d = new double[4];
        for (int i = 0; i < 4; i++) { s[i] = pts[i].x + pts[i].y; d[i] = pts[i].y - pts[i].x; }
        rect[0] = pts[argMin(s)]; rect[2] = pts[argMax(s)];
        rect[1] = pts[argMin(d)]; rect[3] = pts[argMax(d)];
        return rect;
    }

    private int argMin(double[] arr) { int i = 0; for (int j = 1; j < arr.length; j++) if (arr[j] < arr[i]) i = j; return i; }
    private int argMax(double[] arr) { int i = 0; for (int j = 1; j < arr.length; j++) if (arr[j] > arr[i]) i = j; return i; }

    // 그레이스케일 → 이진화 (128 threshold)
    private Bitmap preprocessBinary(Bitmap src) {
        Bitmap gray = preprocessForOcr(src);
        Bitmap bin = gray.copy(Bitmap.Config.ARGB_8888, true);
        int w = bin.getWidth(), h = bin.getHeight();
        int[] pixels = new int[w * h];
        bin.getPixels(pixels, 0, w, 0, 0, w, h);
        for (int i = 0; i < pixels.length; i++) {
            int r = (pixels[i] >> 16) & 0xFF;
            pixels[i] = r > 128 ? 0xFFFFFFFF : 0xFF000000;
        }
        bin.setPixels(pixels, 0, w, 0, 0, w, h);
        gray.recycle();
        return bin;
    }

    // 이미지 전처리: 그레이스케일 → 대비 강화 → ML Kit 투입
    private Bitmap preprocessForOcr(Bitmap src) {
        // 1. 그레이스케일
        Bitmap gray = Bitmap.createBitmap(src.getWidth(), src.getHeight(), Bitmap.Config.ARGB_8888);
        Canvas c1 = new Canvas(gray);
        ColorMatrix cmGray = new ColorMatrix();
        cmGray.setSaturation(0);
        Paint p1 = new Paint();
        p1.setColorFilter(new ColorMatrixColorFilter(cmGray));
        c1.drawBitmap(src, 0, 0, p1);

        // 2. 대비 강화 (scale 1.5, offset -40)
        Bitmap contrast = Bitmap.createBitmap(gray.getWidth(), gray.getHeight(), Bitmap.Config.ARGB_8888);
        Canvas c2 = new Canvas(contrast);
        ColorMatrix cmContrast = new ColorMatrix(new float[]{
            1.5f, 0,    0,    0, -40,
            0,    1.5f, 0,    0, -40,
            0,    0,    1.5f, 0, -40,
            0,    0,    0,    1,   0
        });
        Paint p2 = new Paint();
        p2.setColorFilter(new ColorMatrixColorFilter(cmContrast));
        c2.drawBitmap(gray, 0, 0, p2);
        gray.recycle();

        return contrast;
    }

    private String postProcess(String raw) {
        if (raw == null || raw.isEmpty()) return "";
        StringBuilder sb = new StringBuilder();
        for (String line : raw.split("\n")) {
            String t = line.trim();
            if (t.length() <= 1) continue;
            boolean hasLetter = false;
            for (char c : t.toCharArray()) {
                if (Character.isLetter(c)) { hasLetter = true; break; }
            }
            if (hasLetter) sb.append(t).append("\n");
        }
        return sb.toString().trim();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (recognizer != null) recognizer.close();
    }
}
