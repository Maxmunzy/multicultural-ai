"""가정통신문 일괄 변환 (ODT 경로).

backend.app.services.parser 재사용 — 단일 진실 소스. HWP→PDF→pdfplumber
경로의 글자 중복("22002266학학년년도도") + 셀 구분자(`|`) 문제 회피.

흐름:
  - .hwp / .hwpx → LibreOffice 배치(30개씩) → ODT → content.xml 직접 파싱
  - .pdf → pdfplumber 직접
  - .jpg / .png / .xlsx / .xls / .doc / .docx → 스킵

컨테이너 안에서 실행:
  docker compose exec -T backend python /app/scripts/batch_convert.py \\
      "<입력폴더>" "<출력폴더>"
"""
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

# backend.parser 재사용 — ODT 추출 + dedup 룰 단일 진실 소스
sys.path.insert(0, "/app")
from app.services.parser import (  # noqa: E402
    LIBREOFFICE_TIMEOUT_SECONDS,
    ParserError,
    _odt_to_text,
    _pdf_to_text,
    normalize,
)


def _disable_core_dump() -> None:
    """LibreOffice ODT 변환 후 H2Orestart cleanup 버그로 segfault 발생 시
    1GB+ 메모리 덤프가 wsl-crashes 폴더에 누적되는 것 방지.
    배치 변환 시 100건이면 100GB 덤프 → 디스크 가득 → Docker 마비.
    """
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


SKIP_EXTS = {".jpg", ".jpeg", ".png", ".xlsx", ".xls", ".doc", ".docx"}
HWP_EXTS = {".hwp", ".hwpx"}
PDF_EXTS = {".pdf"}
BATCH_SIZE = 30  # LibreOffice 배치 크기 — 시동 비용 분산 (BATCH_MODE=batch 일 때)

# 변환 모드: BATCH_MODE 환경변수
#   "batch"  — 30개씩 묶어 LibreOffice 1번 호출 (빠름, 단 한 파일 hang 시 30개 멈춤)
#   "single" — 1개씩 호출 + 파일별 타임아웃 (안정성 ↑, 시동 비용 ↑)
BATCH_MODE = os.environ.get("BATCH_MODE", "single").lower()
SINGLE_TIMEOUT_SEC = int(os.environ.get("SINGLE_TIMEOUT_SEC", "90"))


def libreoffice_batch_to_odt(src_paths: list[Path], out_dir: Path) -> None:
    """한 LibreOffice 세션에서 여러 HWP를 ODT로 일괄 변환.

    preexec_fn=_disable_core_dump — segfault 시 메모리 덤프 안 만듦.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "libreoffice", "--headless",
        "--convert-to", "odt",
        "--outdir", str(out_dir),
    ] + [str(p) for p in src_paths]
    subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=LIBREOFFICE_TIMEOUT_SECONDS * 2,  # 배치라 여유
        preexec_fn=_disable_core_dump,
    )


def libreoffice_single_to_odt(src: Path, out_dir: Path) -> bool:
    """단일 파일 변환 + 타임아웃 — hang 회피용.

    SINGLE_TIMEOUT_SEC 초 안에 ODT 못 만들면 LibreOffice 강제 종료 + False 반환.
    호출부는 False 시 해당 파일을 학습 제외 처리.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "libreoffice", "--headless",
        "--convert-to", "odt",
        "--outdir", str(out_dir),
        str(src),
    ]
    try:
        subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=SINGLE_TIMEOUT_SEC,
            preexec_fn=_disable_core_dump,
        )
    except subprocess.TimeoutExpired:
        # LibreOffice 자식 프로세스 정리 — 다음 파일에 영향 안 가게
        subprocess.run(["pkill", "-f", "soffice"], capture_output=True)
        return False
    return (out_dir / f"{src.stem}.odt").exists()


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: batch_convert.py <input_dir> <output_dir>")
        sys.exit(1)
    src_dir = Path(sys.argv[1])
    txt_dir = Path(sys.argv[2])
    odt_tmp = txt_dir / "_odt_intermediate"

    if not src_dir.exists():
        print(f"입력 폴더 없음: {src_dir}")
        sys.exit(1)

    txt_dir.mkdir(parents=True, exist_ok=True)
    odt_tmp.mkdir(parents=True, exist_ok=True)

    all_files = sorted(p for p in src_dir.iterdir() if p.is_file())
    skipped = [p for p in all_files if p.suffix.lower() in SKIP_EXTS]
    pdfs_all = [p for p in all_files if p.suffix.lower() in PDF_EXTS]
    hwps_all = [p for p in all_files if p.suffix.lower() in HWP_EXTS]
    other = [
        p for p in all_files
        if p.suffix.lower() not in SKIP_EXTS | PDF_EXTS | HWP_EXTS
    ]

    # 이미 .txt 출력 있으면 재변환 스킵 (디스크 가득으로 중간 멈췄던 경우 재개에 효율)
    pdfs = [p for p in pdfs_all if not (txt_dir / f"{p.stem}.txt").exists()]
    hwps = [p for p in hwps_all if not (txt_dir / f"{p.stem}.txt").exists()]
    already_done = (len(pdfs_all) - len(pdfs)) + (len(hwps_all) - len(hwps))

    print(f"입력: {src_dir}")
    print(f"출력: {txt_dir}")
    print(
        f"  총 {len(all_files)}개 (스킵 {len(skipped)} / PDF {len(pdfs_all)} / "
        f"HWP {len(hwps_all)} / 기타 {len(other)}) — 이미 변환됨 {already_done}, 재개 {len(pdfs) + len(hwps)}"
    )

    failed: list[tuple[str, str]] = []
    success = 0

    # ODT 이미 있으면 LibreOffice 호출 skip — 부분 진행분 (예: 중간 멈췄던 ODT) 보존
    hwps_to_convert = [p for p in hwps if not (odt_tmp / f"{p.stem}.odt").exists()]
    odt_already = len(hwps) - len(hwps_to_convert)
    if odt_already:
        print(f"  ODT 이미 변환됨: {odt_already}개 (재변환 skip)")

    # HWP/HWPX → ODT 변환 (mode 분기)
    if hwps_to_convert:
        print(f"\n[1/2] LibreOffice ODT 변환 (mode={BATCH_MODE})")
        if BATCH_MODE == "single":
            t_total = time.time()
            for i, src in enumerate(hwps_to_convert, 1):
                t0 = time.time()
                ok = libreoffice_single_to_odt(src, odt_tmp)
                if not ok:
                    failed.append((src.name, f"ODT 변환 실패 (타임아웃 {SINGLE_TIMEOUT_SEC}s 또는 hang)"))
                if i % 20 == 0:
                    print(f"  진행: {i}/{len(hwps_to_convert)} ({time.time() - t_total:.0f}s)")
            print(f"  단일 변환 완료: {len(hwps_to_convert)}개 ({time.time() - t_total:.0f}s)")
        else:
            # batch mode
            for i in range(0, len(hwps_to_convert), BATCH_SIZE):
                chunk = hwps_to_convert[i:i + BATCH_SIZE]
                t0 = time.time()
                try:
                    libreoffice_batch_to_odt(chunk, odt_tmp)
                except subprocess.TimeoutExpired:
                    print(f"  배치 {i // BATCH_SIZE + 1}: 타임아웃")
                print(f"  배치 {i // BATCH_SIZE + 1} ({len(chunk)}개): {time.time() - t0:.1f}s")

    # 텍스트 추출 — PDF는 직접, HWP는 ODT에서
    print(f"\n[2/2] 텍스트 추출")
    pdf_targets: list[tuple[Path, Path]] = [(p, p) for p in pdfs]
    for src in hwps:
        odt_path = odt_tmp / f"{src.stem}.odt"
        if odt_path.exists():
            pdf_targets.append((odt_path, src))
        else:
            failed.append((src.name, "ODT 변환 실패"))

    for i, (artifact, src) in enumerate(pdf_targets, 1):
        try:
            if artifact.suffix.lower() == ".pdf":
                raw = _pdf_to_text(artifact)
            else:
                raw = _odt_to_text(artifact)
            text = normalize(raw)
            if not text:
                failed.append((src.name, "빈 텍스트"))
                continue
            (txt_dir / f"{src.stem}.txt").write_text(text, encoding="utf-8")
            success += 1
        except ParserError as error:
            failed.append((src.name, str(error)[:80]))
        except Exception as error:  # noqa: BLE001 — 일괄 처리 흐름 유지
            failed.append((src.name, f"{type(error).__name__}: {str(error)[:60]}"))
        if i % 30 == 0:
            print(f"  진행: {i}/{len(pdf_targets)}")

    # ODT 임시 정리 — 폴더당 수십~수백 MB, 1000개+ 변환 시 GB 단위로 디스크 부담
    if odt_tmp.exists():
        shutil.rmtree(odt_tmp, ignore_errors=True)

    print(f"\n결과")
    print(f"  성공: {success}/{len(pdf_targets)}")
    print(f"  실패: {len(failed)}")
    if failed:
        print("\n실패 목록:")
        for name, reason in failed[:15]:
            print(f"  - {name[:55]}: {reason}")
        if len(failed) > 15:
            print(f"  ... 외 {len(failed) - 15}개")


if __name__ == "__main__":
    main()
