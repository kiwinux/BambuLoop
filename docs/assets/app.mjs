import { requestJob, resetWorker } from "./client.mjs";

// ============================================================
// i18n — UI text translations (KO ↔ EN)
// ============================================================
const I18N = {
  ko: {
    github_project: 'GitHub에서 BambuLoop 열기',
    contribute_heading: 'BambuLoop 개발에 참여하세요',
    contribute_message: '현재 H2S를 지원합니다. UI 번역이나 지원 예정 모델인 H2D·H2C·H3C·X1C·P1S·A1 추가에 함께해 주세요.',
    view_roadmap: '로드맵 보기',
    contribution_guide: '기여 안내 (영문)',
    dismiss_notice: '이 안내 닫기',
    job_count: '작업 수',
    total_prints: '총 인쇄',
    estimated_size: '예상 크기',
    generate_dry: '▶ 생성',
    generating: '생성 중…',
    checking: '검사 중…',
    page_title: 'BambuLoop — Bambu Lab H2S 자동 반복 인쇄',
    sound_preview_title: '브라우저에서 미리듣기',
    privacy_heading: '개인정보 처리방침',
    privacy_files: '선택한 G-code·3MF 파일과 생성된 결과 파일은 브라우저 안에서만 처리되며 외부 서버로 전송되지 않습니다.',
    developer_notice: '개발자는 BambuLoop 사용으로 발생하는 문제에 대해 책임을 지지 않습니다.',
    panel_upload: '파일',
    verify_plate: '첫 인쇄에서 원본 빌드 플레이트 확인',
    part_fan: '파트 팬', aux_fan: '보조 팬', chamber_fan: '챔버 팬', no_saved_melodies: '저장된 멜로디 없음',
    choose_files: '파일을 선택하거나 여기에 놓으세요',
    file_types: 'G-code · 슬라이싱된 3MF · 브라우저에서 처리',
    cooling_wait_hint: '1~30회 · 기본 5회',
    purge_source: '슬라이서 파일의 필라멘트별 퍼징 설정을 사용합니다.',
    melody_use: '저장한 멜로디는 사운드 목록에서 선택할 수 있습니다.',
    panel_settings: '반복 인쇄 설정',
    section_cooling: '냉각 시퀀스',
    section_eject: '분리(밀어내기) 시퀀스',
    section_reheat: '재가열 / 리셋',
    section_sound: '사운드 알림 (M1006)',
    bed_detach_temp: '베드 분리 온도',
    chamber_temp: '챔버 식힘 온도',
    bed_size_x: '베드 크기 X',
    bed_size_y: '베드 크기 Y',
    method: '방식',
    x_passes: 'X 패스 수',
    z_steps: 'Z 하강 단수',
    back_overhang: '베드 후방 오버행',
    front_overhang: '베드 전방 오버행',
    btn_generate: '통합 G-code 생성',
    btn_dryrun: '드라이런 파일 생성',
    btn_reset: '초기화',
    btn_download: '{ext} 파일 다운로드',
    btn_custom_melody: '커스텀 멜로디 만들기',
    modal_melody_builder: '커스텀 멜로디 빌더',
    btn_save_melody: '멜로디 저장',
    btn_new_melody: '새 멜로디',
    btn_preview_browser: '🔊 브라우저 미리듣기',
    btn_preview_printer: '📥 프린터 G-code 다운로드',
    result_complete: '생성 완료',
    result_filename: '파일명',
    result_size: '크기',
    result_lines: '총 라인',
    result_copies: '총 인쇄',
    sound_event_start: '첫 인쇄 시작',
    sound_event_done: '프린팅 완료 (냉각 직전)',
    sound_event_cool: '냉각 완료 (분리 직전)',
    sound_event_sweep: '스윕 완료 (재가열 직전)',
    sound_event_restart: '재시작 (다음 인쇄 직전)',
    sound_event_end: '마지막 인쇄 종료',
    safety_moves: '이동 명령',
    safety_bbox: '실제 BBox',
    safety_printable: '인쇄 영역',
    warning_bounds: '일반 이동 경고 범위',
    warning_margin: '여유 마진',
    warning_margin_help: '일반 이동의 X·Y 양방향과 Z 상한에 적용됩니다. 기준 범위를 이 거리만큼 넘는 이동까지 노란색으로 표시합니다.',
    safety_ok: '✅ 모든 GCODE 이동이 정상 범위입니다',
    safety_expected: '예상된 영역 밖 이동',
    safety_soft: '영역 밖',
    safety_hard: '충돌 위험',
    safety_details: '상세',
    safety_recheck: '재검증',
    sweep_preview: '스윕 미리보기',
    sweep_play: '▶ 재생',
    sweep_pause: '⏸ 일시정지',
    sweep_speed: '속도',
    sweep_collapse: '접기 ▾',
    sweep_expand: '펼치기 ▸',
    catalog_all: '전체 (기본 + 커스텀)',
    catalog_builtin: '기본 프리셋만',
    catalog_custom: '내 커스텀 멜로디만',
    catalog_label: '🔊 카탈로그 다운로드',
    btn_catalog: '↓ 카탈로그 G-code 다운로드',
    sound_keep_default: '🔇 (Bambu 기본값 유지)',
    m73_section: 'M73 진행률 재계산',
    m73_override: '사이클당 추가 시간 (분)',
    modal_melody_label: '멜로디',
    parking_z_group: '파킹 Z 계산',
    parking_z_min: '파킹 Z 최소값',
    parking_z_clearance: '인쇄물 위 여유',
    parking_z_min_hint: '절대 baseline (작은 인쇄물 보호)',
    parking_z_clearance_hint: '큰 인쇄물에 자동 여유 추가',
  },
  en: {
    github_project: 'BambuLoop on GitHub',
    contribute_heading: 'Contribute to BambuLoop',
    contribute_message: 'BambuLoop supports the H2S today. Help translate the interface or contribute to planned support for the H2D, H2C, H3C, X1C, P1S, and A1.',
    view_roadmap: 'View roadmap',
    contribution_guide: 'Contribution guide',
    dismiss_notice: 'Dismiss this notice',
    job_count: 'JOBS',
    total_prints: 'TOTAL PRINTS',
    estimated_size: 'EST. SIZE',
    generate_dry: '▶ Generate',
    generating: 'Generating…',
    checking: 'Checking…',
    page_title: 'BambuLoop — Repeat Printing for Bambu Lab H2S',
    sound_preview_title: 'Preview in browser',
    privacy_heading: 'Privacy policy',
    privacy_files: 'The G-code and 3MF files you select, and the files you generate, are processed in your browser. They are never sent to an external server.',
    developer_notice: 'The developer accepts no responsibility for any issues arising from the use of BambuLoop.',
    panel_upload: 'Files',
    verify_plate: 'Check the source build plate on the first print',
    part_fan: 'Part fan', aux_fan: 'Auxiliary fan', chamber_fan: 'Chamber fan', no_saved_melodies: 'No saved melodies',
    choose_files: 'Choose files or drop them here',
    file_types: 'G-code · sliced 3MF · processed in this browser',
    cooling_wait_hint: '1–30 waits · default 5',
    purge_source: 'Uses the filament purge settings from the sliced file.',
    melody_use: 'Saved melodies appear in the sound lists.',
    panel_settings: 'Repeat print settings',
    section_cooling: 'Cooling Sequence',
    section_eject: 'Eject (Sweep) Sequence',
    section_reheat: 'Reheat / Reset',
    section_sound: 'Sound Notifications (M1006)',
    bed_detach_temp: 'Bed Detach Temperature',
    chamber_temp: 'Chamber Cool-down Temp',
    bed_size_x: 'Bed Size X',
    bed_size_y: 'Bed Size Y',
    method: 'Method',
    x_passes: 'X Pass Count',
    z_steps: 'Z Descent Steps',
    back_overhang: 'Back Overhang',
    front_overhang: 'Front Overhang',
    btn_generate: 'Generate G-code',
    btn_dryrun: 'Generate dry-run',
    btn_reset: 'Reset',
    btn_download: 'Download {ext} file',
    btn_custom_melody: 'Create Custom Melody',
    modal_melody_builder: 'Custom Melody Builder',
    btn_save_melody: 'Save melody',
    btn_new_melody: 'New melody',
    btn_preview_browser: '🔊 Browser Preview',
    btn_preview_printer: '📥 Download Printer G-code',
    result_complete: 'File generated',
    result_filename: 'Filename',
    result_size: 'Size',
    result_lines: 'Total Lines',
    result_copies: 'Total Prints',
    sound_event_start: 'First print start',
    sound_event_done: 'Print Done (before cooling)',
    sound_event_cool: 'Cool Done (before eject)',
    sound_event_sweep: 'Sweep Done (before reheat)',
    sound_event_restart: 'Restart (before next print)',
    sound_event_end: 'Final print end',
    safety_moves: 'Move Commands',
    safety_bbox: 'Actual BBox',
    safety_printable: 'Printable Area',
    warning_bounds: 'Ordinary move warning range',
    warning_margin: 'Warning margin',
    warning_margin_help: 'For ordinary moves, this distance extends the yellow warning range in X, Y and upper Z.',
    safety_ok: '✅ All GCODE moves are within their permitted ranges',
    safety_expected: 'Expected out-of-area moves',
    safety_soft: 'Out of Area',
    safety_hard: 'Collision Risk',
    safety_details: 'Details',
    safety_recheck: 'Re-validate',
    sweep_preview: 'Sweep preview',
    sweep_play: '▶ Play',
    sweep_pause: '⏸ Pause',
    sweep_speed: 'Speed',
    sweep_collapse: 'Collapse ▾',
    sweep_expand: 'Expand ▸',
    catalog_all: 'All (Built-in + Custom)',
    catalog_builtin: 'Built-in Only',
    catalog_custom: 'My Custom Only',
    catalog_label: '🔊 Catalog Download',
    btn_catalog: '↓ Download Catalog G-code',
    sound_keep_default: '🔇 (Keep Bambu Default)',
    m73_section: 'M73 Progress Recalculation',
    m73_override: 'Additional Time per Cycle (min)',
    modal_melody_label: 'Melody',
    parking_z_group: 'Parking Z Calculation',
    parking_z_min: 'Parking Z Minimum',
    parking_z_clearance: 'Clearance Above Print',
    parking_z_min_hint: 'Absolute baseline (protects small prints)',
    parking_z_clearance_hint: 'Auto-adds clearance for tall prints',
  },
};

let currentLang = document.documentElement.lang;
try {
  if (localStorage.getItem('bambuloop_lang') === 'ko') currentLang = 'ko';
} catch {
  // The static English interface also works without preference storage.
}

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || I18N['ko'][key] || key;
}

const KO_TO_EN = {
  "통합 G-code 생성": "Generate G-code",
  "드라이런 파일 생성": "Generate dry-run",
  "초기화": "Reset",
  "↓ 다운로드": "↓ Download",
  "↓ 카탈로그 G-code 다운로드": "↓ Download Catalog G-code",
  "↻ 재검증": "↻ Re-validate",
  "취소": "Cancel",
  "상세": "Details",
  "속도": "Speed",
  "방식": "Method",
  "길이:": "Length:",
  "생성 완료": "File generated",
  "파일명:": "Filename:",
  "크기:": "Size:",
  "총 라인:": "Total Lines:",
  "총 인쇄:": "Total Prints:",
  "이동 명령:": "Move Commands:",
  "실제 BBox:": "Actual BBox:",
  "인쇄 영역:": "Printable Area:",
  "브라우저 미리듣기": "Browser Preview",
  "프린터 미리듣기": "Printer Preview",
  "냉각 시퀀스": "Cooling Sequence",
  "분리(밀어내기) 시퀀스": "Eject (Sweep) Sequence",
  "리셋 / 안전 / 재가열": "Reset / Safety / Reheat",
  "사운드 알림 (M1006)": "Sound Notifications (M1006)",
  "▸ 스윕 미리보기": "▸ Sweep Preview",
  "▸ 반복 사이클": "▸ Repeat Cycles",
  "▸ 시작 시퀀스 최적화": "▸ Start Sequence Optimization",
  "▸ 저장된 커스텀 멜로디 (": "▸ Saved Custom Melodies (",
  "▸ 🎹 피아노 (들리는 음역대 C4~D6)": "▸ 🎹 Piano (audible range C4~D6)",
  "▶ 재생": "▶ Play",
  "▶ 생성": "▶ Generate",
  "접기 ▾": "Collapse ▾",
  "첫 인쇄 시작": "First print start",
  "프린팅 완료 (냉각 직전)": "Print Done (before cooling)",
  "냉각 완료 (분리 직전)": "Cool Done (before eject)",
  "스윕 완료 (재가열 직전)": "Sweep Done (before reheat)",
  "재시작 (다음 인쇄 직전)": "Restart (before next print)",
  "마지막 인쇄 종료": "Final print end",
  "커스텀 멜로디 만들기": "Create Custom Melody",
  "커스텀 멜로디 빌더": "Custom Melody Builder",
  "멜로디 저장": "Save melody",
  "새 멜로디": "New melody",
  "🔊 브라우저 미리듣기": "🔊 Browser Preview",
  "📥 프린터 G-code 다운로드": "📥 Download Printer G-code",
  "+ 휴지": "+ Rest",
  "멜로디 이름": "Melody Name",
  "음,": "notes,",
  "0.2초": "0.2s",
  "0초": "0s",
  "위에서 음을 추가하세요": "Add notes above",
  "저장된 멜로디 없음": "No saved melodies — create one above",
  "음표를 추가/순서변경/삭제해서 멜로디를 만드세요.": "Add / reorder / delete notes to compose your melody.",
  "건반을 클릭하면 즉시 노트 추가 + 미리듣기. 길이는 아래 슬라이더로 미리 설정.": "Click a key to instantly add a note with preview. Set length on the slider first.",
  "는 즉시 가능 (모터 음과 다름),": "is instant (differs from motor sound),",
  "는 G-code 다운로드 후 프린터에서 실행.": "requires downloading G-code and running on the printer.",
  "개, 무제한 추가)": ", unlimited)",
  "베드 분리 온도": "Bed Detach Temperature",
  "냉각 반복 횟수": "Cooling Retries",
  "챔버 냉각 목표": "Chamber Cool Target",
  "0 = 챔버 대기 안 함": "0 = No chamber wait",
  "팬 제어 (개별 ON/OFF)": "Fan Control (per-fan ON/OFF)",
  "파트 쿨링": "Part Cooling",
  "AUX 보조 팬": "AUX Aux Fan",
  "챔버 배기": "Chamber Exhaust",
  "토글 OFF 시 명시적 M106 P<n> S0 전송 (잔류 상태 차단)": "When OFF, send explicit M106 P<n> S0 (block residual state)",
  "파킹 Z 최소값": "Parking Z Minimum",
  "인쇄물 위 여유": "Clearance Above Print",
  "베드 X (mm)": "Bed X (mm)",
  "베드 Y (mm)": "Bed Y (mm)",
  "후방 베드밖 거리": "Back Off-bed Distance",
  "Y = (bedY + this value) — 헤드를 베드 밖으로 보낸 뒤 Z 하강 (인쇄물 누름 방지)": "Y = (bedY + this) — Move head off-bed before lowering Z (avoid pressing print)",
  "전방 베드밖 거리": "Front Off-bed Distance",
  "Y=−이값 — 베드 앞면 넘어 인쇄물 낙하 보장": "Y=−this — Pushes past front edge to ensure part falls off",
  "Y축 스윕 횟수 (X 분할)": "Y-axis sweep count (X divisions)",
  "한 단계에서 X 위치 몇 번 분할하여 스윕할지": "How many X positions to sweep at each Z step",
  "하강 단계 수": "Descent Steps",
  "위→아래 분할 횟수 (1=한번에)": "Top→bottom divisions (1 = single pass)",
  "파킹 Z 여유": "Parking Z Clearance",
  "XY 파킹 시 인쇄물 위 여유 (mm)": "Clearance above print for XY parking (mm)",
  "최종 스윕 Z 오프셋": "Final Sweep Z Offset",
  "베드 표면 위 노즐 높이 (mm)": "Nozzle height above bed surface (mm)",
  "스윕 속도": "Sweep Speed",
  "분리 후 일시정지 (Handy 카메라로 검증)": "Pause after eject (verify with Handy camera)",
  "M400 U1 삽입. Bambu Handy/Studio에서 'Resume'으로 재개": "Insert M400 U1. Resume via Bambu Handy/Studio.",
  "XY 재호밍 (인쇄 사이)": "XY Re-home (between prints)",
  "Z 재호밍 (느림, 정밀 필요 시)": "Z Re-home (slow, only when precision needed)",
  "플러싱 + 클리닝 (Bambu 표준)": "Purge + Clean (Bambu standard)",
  "노즐 클리닝 (G150.1)": "Nozzle Cleaning (G150.1)",
  "Bambu 플러싱 블록에 이미 포함됨. 플러싱 fallback 시에만 개별 적용.": "Already in Bambu purge block. Only applied separately on purge fallback.",
  "Fallback 시만 사용": "Fallback Only",
  "Bambu 블록 없을 때 수동 E 압출량 (legacy, 무시됨)": "Manual E extrude length when Bambu block absent (legacy, ignored)",
  "M73 진행률 재계산": "M73 Progress Recalculation",
  "항상 ON": "always ON",
  "— 인쇄 사이 POST_PRINT 시간만 미세조정 가능.": "— only POST_PRINT time between prints is adjustable.",
  "원본 G-code 헤더의 시간을 기반으로 전체 bambuloop 누적 진행률 자동 계산.": "Auto-recalculate cumulative bambuloop progress based on original G-code header time.",
  "사이클당 추가 시간 (분)": "Additional Time per Cycle (min)",
  "0 = 자동 추정 (냉각/분리/재가열/리셋 합산)": "0 = Auto-estimate (cool/eject/reheat/reset sum)",
  "🔊 카탈로그 다운로드": "🔊 Catalog Download",
  "전체 (기본 + 커스텀)": "All (Built-in + Custom)",
  "기본 프리셋만": "Built-in Only",
  "내 커스텀 멜로디만": "My Custom Only",
  "각 프리셋 2초 간격 순차 재생.": "Sequentially play each preset with 2s interval.",
  "각 이벤트마다 다른 멜로디를 선택할 수 있습니다.": "Select a different melody for each event.",
  "는 Bambu 정품 사운드를 우리 사운드로 교체합니다.": "replaces Bambu default sound with our sound.",
  "시작/종료 사운드": "Start/End Sound",
  "다중 스윕": "Multi Sweep",
  "좌우 교차": "Edge-to-Center",
  "좌우 교차 (바닥 고정)": "Edge-to-Center (Bottom)",
  "바닥 반복 (낮은 오브젝트)": "Bottom Only (short objects)",
  "단일 스윕": "Single Sweep",
  "지그재그": "Zigzag",
  "사용 안 함": "None",
  "드라이런 옵션": "⚡ DRY-RUN OPTIONS",
  "실제 인쇄 없이 자동화 시퀀스만 검증합니다.": "Validate automation sequence only (no actual print).",
  "→ 필라멘트 없이 순수 가열 + 스윕 + 클리닝 테스트. 종료 시 간소화됨.": "→ Pure heat + sweep + clean test without filament. Simplified termination.",
  "시뮬레이션 — 인쇄높이": "Simulation — Print Height",
  "⚡ 최소 시작 시퀀스 (캘리브레이션 생략)": "⚡ Minimal Start (skip calibration)",
  "제거:": "Removed:",
  "추가 제거:": "Also removed:",
  "오토 레벨링(G29), 유량/진동 보정, 필라멘트 프라이밍, 노즐 와이프 반복": "Auto-leveling (G29), flow/vibration calib, filament priming, nozzle wipe loop",
  "유지:": "Kept:",
  "G28 (Z/XY 호밍), 가열, AMS 로드": "G28 (Z/XY home), heating, AMS load",
  "🚫 AMS 필라멘트 로드 스킵": "🚫 Skip AMS Filament Load",
  "T0/M620/M621 (AMS 슬롯 선택), 플러싱 블록(E45)": "T0/M620/M621 (AMS slot select), purge block (E45)",
  "시작 G-code: 기본값 (업로드 파일 없음)": "Start G-code: defaults (no uploaded file)",
  "는 M190/M109 등 온도 도달 대기를 생략하여 빠른 검증이 가능합니다.": "skips M190/M109 wait-for-temp commands for fast validation.",
  "냉각 시퀀스 포함": "Include Cooling",
  "└ 냉각 완료 대기 (M190 R)": "└ Wait for cool done (M190 R)",
  "재가열 시퀀스 포함": "Include Reheat",
  "└ 재가열 완료 대기 (M190/M109)": "└ Wait for reheat done (M190/M109)",
  "대기 OFF": "wait OFF",
  "분리(스윕) 시퀀스 포함": "Include Eject (Sweep)",
  "리셋 (재호밍/퍼지) 포함": "Include Reset (re-home/purge)",
  "사이클 수": "Cycle Count",
  "1~10 회 반복 — 각 사이클 사이에 가짜 body 삽입": "1–10 cycles — fake body inserted between cycles",
  "포함할 phase를 선택하세요.": "Select phases to include.",
  "가비지 캔으로 필라멘트 배출(E45) + G150.1 와이프 — 베드에 잔여물 없음.": "Dump filament to garbage can (E45) + G150.1 wipe — no residue on bed.",
  "값을 바꾸면 즉시 반영됩니다. 헤드 마커는 실제 동작 순서대로 움직입니다.": "Changes apply instantly. Head marker moves in actual operation order.",
  "Z단": "Z",
  "mm /\n        노즐": "mm /\n        Nozzle",
  "°C / 베드": "°C / Bed"
};

// Static labels that predate data-i18n keep their original DOM nodes in both languages.
let legacyLabels;
function translateTextNodes() {
  if (!legacyLabels) {
    legacyLabels = [];
    const englishToKorean = new Map(Object.entries(KO_TO_EN).map(([ko, en]) => [en, ko]));
    const nodes = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = nodes.nextNode(); node; node = nodes.nextNode()) {
      if (node.parentElement?.closest('script, style, [data-i18n]')) continue;
      const original = node.nodeValue;
      const key = original.trim();
      if (englishToKorean.has(key)) {
        legacyLabels.push({node, en: original, ko: original.replace(key, () => englishToKorean.get(key))});
      }
    }
  }
  for (const item of legacyLabels) item.node.nodeValue = item[currentLang];
}

function applyI18n() {
  // Marked data-i18n elements
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = (el.disabled && el.dataset.busyI18n) || el.dataset.i18n;
    const val = t(key);
    if (val) el.textContent = val;
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  const cmName = document.getElementById('cmName');
  cmName.placeholder = currentLang === 'en' ? cmName.dataset.placeholderEn : cmName.dataset.placeholderKo;
  translateTextNodes();
  document.documentElement.lang = currentLang;
  // Update the toggle button label
  const tb = document.getElementById('langToggle');
  if (tb) {
    tb.lang = currentLang === 'ko' ? 'en' : 'ko';
    tb.textContent = currentLang === 'ko' ? 'EN' : '한국어';
  }
  const roadmap = document.getElementById('roadmapLink');
  roadmap.href = currentLang === 'ko'
    ? 'https://github.com/kiwinux/BambuLoop/blob/main/README.ko.md#로드맵--기여'
    : 'https://github.com/kiwinux/BambuLoop#roadmap--contributing';
}

// ============================================================
// Tooltips (ⓘ icon) — KO/EN dictionary + hover handler
// ============================================================
const TIP_TEXTS = {
  cooling_retries_tip: {
    ko: '분리 전에 같은 베드 온도로 대기를 반복합니다. 기본값은 5회입니다.',
    en: 'Repeats the wait for the target bed temperature before ejection. Default: 5 waits.',
  },
  bed_detach_tip: {
    ko: '<strong>베드 분리 온도</strong><br>인쇄가 끝난 후 베드를 이 온도까지 식힙니다. 베드와 인쇄물의 열팽창 차이로 자연스럽게 분리됩니다.<br><br>· PLA: 35°C<br>· PETG: 35°C<br>· ABS/ASA: 40°C<br><br>40°C가 안전 상한입니다 (그 이상에서 분리 시도 시 인쇄물이 베드에 융착될 수 있음).<br><br>⚙️ <em>Marlin/Klipper의 M190 R 타임아웃을 우회하기 위해 M190 R을 여러 번 반복 호출합니다. 반복 횟수는 아래 "냉각 대기 반복 횟수" 필드에서 조정 가능합니다.</em>',
    en: '<strong>Bed Detach Temperature</strong><br>Cools the bed to this temperature after print. Differential thermal contraction releases the part naturally.<br><br>· PLA: 35°C<br>· PETG: 35°C<br>· ABS/ASA: 40°C<br><br>40°C is the safe upper limit (above this, parts may fuse to the bed).<br><br>⚙️ <em>To bypass the M190 R timeout, the tool calls M190 R multiple times with the target value. Adjust the retry count in the "Cooling Wait Retries" field below.</em>',
  },
  parking_z_tip: {
    ko: '<strong>파킹 Z 계산</strong><br>인쇄 후 노즐을 어느 높이로 들어올릴지 결정합니다.<br><br><span style="color:#5fc8ff;">최소값(minimum)</span>: 절대 baseline. 작은 인쇄물에서도 노즐이 베드에 너무 가까이 있지 않게 합니다.<br><br><span style="color:#ffaa55;">여유(clearance)</span>: 인쇄물 위 추가 공간. 큰 인쇄물에서는 baseline으로 부족하므로 (인쇄물 높이 + 여유)로 자동 계산.<br><br>둘 중 큰 값이 적용되어 작은 인쇄물 + 큰 인쇄물 모두 안전합니다.',
    en: '<strong>Parking Z Calculation</strong><br>Determines how high to lift the nozzle after print.<br><br><span style="color:#5fc8ff;">Minimum</span>: absolute baseline. Even with tiny prints, the nozzle stays this far from the bed.<br><br><span style="color:#ffaa55;">Clearance</span>: extra space above the print. For tall prints, the baseline is not enough; (print_height + clearance) is used instead.<br><br>The larger of the two is applied — safe for both small and large prints.',
  },
  eject_z_offset_tip: {
    ko: '<strong>최종 스윕 Z 오프셋</strong><br>분리 스윕의 마지막 단계에서 노즐과 베드 사이 거리. 0에 가까울수록 강하게 밀어냅니다.<br><br>· 0.4mm 권장 (일반)<br>· 0.2mm (얇은 인쇄물 - 강한 분리)<br>· 0.6mm (베드 보호 우선)<br><br>너무 작으면 노즐이 베드에 닿을 위험이 있습니다.',
    en: '<strong>Final Sweep Z Offset</strong><br>Distance between nozzle and bed on the last sweep step. Closer = stronger push.<br><br>· 0.4mm recommended (default)<br>· 0.2mm (thin parts - aggressive eject)<br>· 0.6mm (bed protection priority)<br><br>Too small risks nozzle-bed contact.',
  },
  initial_z_clearance_tip: {
    ko: '<strong>파킹 Z 여유</strong><br>XY 파킹 시 노즐이 인쇄물 위로 얼마나 떠있을지. 파킹 후 Z를 인쇄물 꼭대기까지 내려서 첫 스윕을 시작합니다.<br><br>· 10mm 권장 (안전 여유)<br>· 너무 작으면 XY 이동 중 인쇄물 측면 충돌 위험<br>· 너무 크면 분리 시간 증가',
    en: '<strong>Parking Z Clearance</strong><br>How high above the print the nozzle parks before sweep. After parking, Z descends to print top for the first sweep pass.<br><br>· 10mm recommended (safety margin)<br>· Too small risks side collision during XY parking<br>· Too large adds time',
  },
  descent_steps_tip: {
    ko: '<strong>하강 단계 수</strong><br>인쇄물 꼭대기에서 최종 Z 오프셋까지 몇 단계로 나누어 하강할지.<br><br>· 4단계 권장 (균형)<br>· 1단계 = 한번에 (빠르지만 거친 분리)<br>· 8단계 = 매우 부드러움 (시간 ↑)<br><br>각 단계마다 Y축 스윕을 실행합니다.',
    en: '<strong>Descent Steps</strong><br>How many steps to descend from print top to final Z offset.<br><br>· 4 steps recommended (balanced)<br>· 1 = single pass (fast but rough)<br>· 8 = very smooth (slower)<br><br>Each step executes Y-axis sweeps.',
  },
  sweep_speed_tip: {
    ko: '<strong>스윕 속도</strong><br>분리 스윕 시 헤드 이동 속도 (mm/min).<br><br>· 3000 mm/min 권장 (50 mm/sec)<br>· 빠를수록 분리력 ↑ (관성)<br>· 너무 빠르면 헤드 점프/스킵 발생 가능',
    en: '<strong>Sweep Speed</strong><br>Head movement speed during eject sweep (mm/min).<br><br>· 3000 mm/min recommended (50 mm/sec)<br>· Faster = more eject force (momentum)<br>· Too fast may cause head skipping',
  },
  x_passes_tip: {
    ko: '<strong>Y축 스윕 횟수 (X 분할)</strong><br>한 Z 단계에서 X축 위치를 몇 번 분할하여 스윕할지.<br><br>· 7회 권장 (베드 X=340mm ÷ 헤드 폭 ~50mm)<br>· 바닥 반복 모드에서는 20~30회 권장 (많이 쓸수록 분리력 ↑)<br>· 적으면 인쇄물이 헤드 사이를 통과해 안 밀릴 수 있음<br>· 많으면 시간 ↑',
    en: '<strong>Y-axis Sweep Count (X Divisions)</strong><br>How many X positions to sweep at each Z step.<br><br>· 7 recommended (bed X=340mm ÷ head width ~50mm)<br>· For bottom-only mode: 20~30 recommended (more sweeps = more force)<br>· Too few may let parts slip between head positions<br>· Too many adds time',
  },
  back_overhang_tip: {
    ko: '<strong>베드 후방 오버행</strong><br>스윕 시작 전 헤드를 베드 뒤쪽 밖으로 얼마나 보낼지.<br><br>Y = (bed_size_y + 이 값)<br><br>· 15mm 권장<br>· 너무 작으면 Z 하강 시 인쇄물을 누름<br>· 너무 크면 후방 한계 스위치 충돌 위험',
    en: '<strong>Back Off-bed Distance</strong><br>How far past the back of the bed to send the head before sweeping.<br><br>Y = (bed_size_y + this value)<br><br>· 15mm recommended<br>· Too small may press the print during Z descent<br>· Too large risks rear limit switch collision',
  },
  front_overhang_tip: {
    ko: '<strong>베드 전방 오버행</strong><br>스윕 종료 시 헤드가 베드 앞쪽 밖으로 얼마나 갈지.<br><br>Y = -(이 값)<br><br>· 5mm 권장<br>· 베드 가장자리만 넘으면 인쇄물 낙하 보장<br>· 작아도 됨 (베드 가장자리에서만 떨어지면 OK)',
    en: '<strong>Front Off-bed Distance</strong><br>How far past the front of the bed the head goes at sweep end.<br><br>Y = -(this value)<br><br>· 5mm recommended<br>· Just past the front edge ensures part drops off<br>· Can be small (just needs to clear edge)',
  },
  fan_tip: {
    ko: '<strong>팬 제어</strong><br>냉각 단계에서 사용할 팬 속도를 0~100%로 지정합니다 (백엔드는 PWM 0~255로 변환).<br><br>· 100% = 풀가동 (빠른 냉각)<br>· 토글 OFF 시 명시적으로 M106 P&lt;n&gt; S0 전송 (이전 인쇄의 잔류 팬 상태 차단)<br><br>P1 = 파트 쿨링, P2 = AUX 보조, P3 = 챔버 배기',
    en: '<strong>Fan Control</strong><br>Fan speeds during cooling, 0~100% (backend converts to PWM 0~255).<br><br>· 100% = full speed (faster cooling)<br>· When toggled OFF, explicit M106 P&lt;n&gt; S0 is sent (blocks residual fan state from previous print)<br><br>P1 = part cooling, P2 = AUX, P3 = chamber exhaust',
  },
};

let _tipPopover = null;
function bindInfoTips() {
  document.querySelectorAll('.info-tip').forEach(el => {
    if (el._tipBound) return;
    el._tipBound = true;
    el.addEventListener('mouseenter', (e) => {
      const key = el.dataset.tip;
      const txt = TIP_TEXTS[key];
      if (!txt) return;
      const html = txt[currentLang] || txt.en || txt.ko || '';
      if (_tipPopover) _tipPopover.remove();
      _tipPopover = document.createElement('div');
      _tipPopover.className = 'info-tip-popover';
      _tipPopover.innerHTML = html;
      document.body.appendChild(_tipPopover);
      const rect = el.getBoundingClientRect();
      let left = rect.right + 8;
      let top = rect.top;
      // Keep within the viewport
      const pw = _tipPopover.offsetWidth;
      const ph = _tipPopover.offsetHeight;
      if (left + pw > window.innerWidth - 10) left = rect.left - pw - 8;
      if (top + ph > window.innerHeight - 10) top = window.innerHeight - ph - 10;
      if (top < 10) top = 10;
      _tipPopover.style.left = left + 'px';
      _tipPopover.style.top = top + 'px';
    });
    el.addEventListener('mouseleave', () => {
      if (_tipPopover) { _tipPopover.remove(); _tipPopover = null; }
    });
  });
}

function setLang(lang) {
  currentLang = lang;
  try {
    localStorage.setItem('bambuloop_lang', lang);
  } catch {
    // Keep the current tab's selection when the browser blocks storage.
  }
  applyI18n();
  // Reload dynamic content
  if (typeof loadSoundPresets === 'function') loadSoundPresets();
  if (typeof renderCmSavedList === 'function') renderCmSavedList();
  if (typeof render === 'function') render();              // 잡 리스트 (라인 라벨 등)
  if (typeof renderSafety === 'function' && lastSafetyData) {
    renderSafety(lastSafetyData, lastSafetyFile);          // 결과 카드 안전 박스
  }
  resultLabels();
  // Generate-button label
  const gb = document.getElementById('generateBtn');
  if (gb && !gb.disabled && !gb.textContent.includes('⟳')) {
    gb.textContent = lang === 'en' ? 'Generate G-code' : '통합 G-code 생성';
  }
  // cmName placeholder
  const cmName = document.getElementById('cmName');
  if (cmName) {
    // Update the name if it was auto-generated (user did not type one)
    const v = cmName.value.trim();
    if (v.startsWith('내 멜로디 ') || v.startsWith('My Melody ')) {
      cmName.value = (typeof suggestNextName === 'function') ? suggestNextName() : v;
    }
  }
  // Refresh note label + time unit
  if (typeof renderCmNoteList === 'function') renderCmNoteList();
  // Sweep controls
  const sweepBtn = document.getElementById('sweepVizToggle');
  if (sweepBtn) {
    const isCollapsed = sweepBtn.textContent.includes('▸') || sweepBtn.textContent.includes('Expand');
    sweepBtn.textContent = isCollapsed ? (lang === 'en' ? 'Expand ▸' : '펼치기 ▸') : (lang === 'en' ? 'Collapse ▾' : '접기 ▾');
  }
  // Sweep play/pause button
  const playBtn = document.getElementById('sweepPlayBtn');
  if (playBtn && typeof sweepViz !== 'undefined') {
    playBtn.textContent = sweepViz.paused
      ? (lang === 'en' ? '▶ Play' : '▶ 재생')
      : (lang === 'en' ? '⏸ Pause' : '⏸ 일시정지');
  }
  // Sweep status (sweep X/N · Z step N/M)
  if (typeof refreshSweepViz === 'function') refreshSweepViz();
}

// Toast i18n helper — accepts a {ko, en} dict or a plain string
function tToast(msg, type) {
  if (typeof msg === 'string') {
    showToast(msg, type);
  } else if (msg && typeof msg === 'object') {
    showToast(msg[currentLang] || msg.en || msg.ko || '', type);
  }
}

// Generic i18n value resolver — accepts a {ko, en, ...} dict (sent by the
// backend via t_dict()) or a plain string (legacy). Picks the right entry
// for the current UI language, falls back to English, then to the input
// itself if nothing matches. New languages added via i18n/<lang>.json
// require no frontend change beyond adding the language to the UI toggle.
function tValue(v, fallback) {
  if (v == null) return fallback || '';
  if (typeof v === 'string') return v;
  if (typeof v === 'object') return v[currentLang] || v.en || fallback || '';
  return fallback || '';
}

// ============================================================
// Custom alert/confirm modal (replaces the native alert/confirm)
// ============================================================
function showAlertModal(title, htmlBody) {
  const modal = document.getElementById('alertModal');
  document.getElementById('alertModalTitle').textContent = title;
  document.getElementById('alertModalBody').innerHTML = htmlBody;
  document.getElementById('alertModalCancel').style.display = 'none';
  const okBtn = document.getElementById('alertModalOk');
  okBtn.textContent = currentLang === 'en' ? 'OK' : '확인';
  modal.style.display = 'flex';
  return new Promise(resolve => {
    const close = () => { modal.style.display = 'none'; resolve(); };
    okBtn.onclick = close;
    document.getElementById('alertModalClose').onclick = close;
  });
}

function showConfirmModal(title, htmlBody, opts) {
  opts = opts || {};
  const modal = document.getElementById('alertModal');
  document.getElementById('alertModalTitle').textContent = title;
  document.getElementById('alertModalBody').innerHTML = htmlBody;
  const cancelBtn = document.getElementById('alertModalCancel');
  const okBtn = document.getElementById('alertModalOk');
  cancelBtn.style.display = 'inline-block';
  cancelBtn.textContent = opts.cancelLabel || (currentLang === 'en' ? 'Cancel' : '취소');
  okBtn.textContent = opts.okLabel || (currentLang === 'en' ? 'Proceed' : '진행');
  modal.style.display = 'flex';
  return new Promise(resolve => {
    const close = (val) => {
      modal.style.display = 'none';
      cancelBtn.onclick = okBtn.onclick = null;
      resolve(val);
    };
    okBtn.onclick = () => close(true);
    cancelBtn.onclick = () => close(false);
    document.getElementById('alertModalClose').onclick = () => close(false);
  });
}

function initContributionNotice() {
  const notice = document.getElementById('contributionNotice');
  notice.hidden = false;
  document.getElementById('dismissContribution').addEventListener('click', event => {
    notice.hidden = true;
    if (event.detail === 0) document.getElementById('projectLink').focus({preventScroll:true});
  });
}

// Toggle button handler (once DOM is ready)
document.addEventListener('DOMContentLoaded', () => {
  const tb = document.getElementById('langToggle');
  if (tb) tb.addEventListener('click', () => setLang(currentLang === 'ko' ? 'en' : 'ko'));
  applyI18n();
  bindInfoTips();
  initContributionNotice();
});

// State management
// ============================================================
const state = {
  jobs: [],   // [{stored_name, original_name, count, info}]
};

// ============================================================
// Toast
// ============================================================
const toast = document.getElementById('toast');
let toastTimer = null;
function showToast(msg, type = '') {
  toast.textContent = msg;
  toast.className = 'toast show ' + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 3500);
}

// ============================================================
// Upload
// ============================================================
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');

['dragenter', 'dragover'].forEach(evt =>
  dropzone.addEventListener(evt, e => { e.preventDefault(); dropzone.classList.add('drag'); }));
['dragleave', 'drop'].forEach(evt =>
  dropzone.addEventListener(evt, e => { e.preventDefault(); dropzone.classList.remove('drag'); }));

dropzone.addEventListener('drop', e => {
  e.preventDefault();
  const files = Array.from(e.dataTransfer.files);
  uploadFiles(files);
});
fileInput.addEventListener('change', e => uploadFiles(Array.from(e.target.files)));

let inputVersion = 0;
let activeGeneration = 0;

function nozzleDifference(first, next) {
  if (!first) return '';
  if (first.nozzle_diameter && next.nozzle_diameter && Math.abs(first.nozzle_diameter - next.nozzle_diameter) > 0.001) {
    return `${first.nozzle_diameter} mm / ${next.nozzle_diameter} mm`;
  }
  for (const key of ['nozzle_flow_type', 'nozzle_hrc']) {
    if (first[key] && next[key] && first[key] !== next[key]) return first[key] + ' / ' + next[key];
  }
  return '';
}

async function uploadFiles(files) {
  if (!files.length) return;
  const version = inputVersion;
  tToast({ko: '파일 읽는 중…', en: 'Reading files…'});
  try {
    const { data } = await requestJob('import', {}, { files });
    if (version !== inputVersion) return;
    const messages = (data.errors || []).map(e => e.filename + ' · ' + tValue(e.message));
    for (const info of data.files) {
      const mismatch = nozzleDifference(state.jobs[0]?.info, info);
      if (mismatch) {
        messages.push(info.original_name + ' · ' + tValue({ko:'노즐 불일치', en:'Nozzle mismatch'}) + ' (' + mismatch + ')');
        requestJob('delete_upload', { stored_name: info.stored_name }).catch(() => {});
      } else {
        state.jobs.push({ stored_name: info.stored_name, original_name: info.original_name, count: 1, info });
      }
    }
    render();
    if (messages.length) {
      await showAlertModal(tValue({ko:'추가하지 못한 파일', en:'Files not added'}),
                           messages.map(escapeHtml).join('<br>'));
    } else {
      tToast({ko: `${data.files.length}개 파일 추가`, en: `${data.files.length} file(s) added`}, 'success');
    }
  } catch (error) {
    if (version === inputVersion) showToast(error.message, 'error');
  } finally {
    fileInput.value = '';
  }
}

document.addEventListener('engine-invalidated', () => {
  ++inputVersion;
  activeGeneration = 0;
  state.jobs = [];
  // Output Blobs remain available for download and can be rechecked by a new worker.
  render();
  showToast(tValue({ko:'처리 엔진이 종료됐습니다. 입력 파일을 다시 선택하세요.',
                    en:'The processing engine stopped. Select your input files again.'}), 'error');
});

document.addEventListener('engine-state', ({ detail }) => {
  const el = document.getElementById('engineStatus');
  el.hidden = detail !== 'loading';
  el.textContent = el.hidden ? '' : tValue({ko:'처리 엔진 불러오는 중…', en:'Loading the processing engine…'});
});

const jobListEl = document.getElementById('jobList');
const sumJobs = document.getElementById('sumJobs');
const sumPrints = document.getElementById('sumPrints');
const sumSize = document.getElementById('sumSize');
const generateBtn = document.getElementById('generateBtn');

function renderPlateSource() {
  const first = state.jobs[0]?.info;
  const enabled = document.getElementById('verify_build_plate').checked;
  const fields = [];
  if (first) {
    fields.push(tValue({ko:'첫 파일 기준', en:'First file'}));
    if (first.source_plate_name) fields.push(first.source_plate_name);
    fields.push(first.bed_type || tValue({ko:'표면 종류 미표기', en:'Surface unspecified'}));
  }
  if (!enabled) fields.push(tValue({ko:'검사 생략', en:'Check omitted'}));
  else if (!first) fields.push(tValue({ko:'선택한 첫 파일의 검사 구간을 사용합니다.', en:'Uses the check in the first selected file.'}));
  else if (!first.has_build_plate_check) fields.push(tValue({ko:'원본에 검사 구간 없음', en:'No check in source'}));
  document.getElementById('plateCheckSource').textContent = fields.join(' · ');
}

document.getElementById('verify_build_plate').addEventListener('change', renderPlateSource);

function render() {
  renderPlateSource();
  jobListEl.innerHTML = '';
  state.jobs.forEach((job, idx) => {
    const el = document.createElement('div');
    el.className = 'job-item';
    el.innerHTML = `
      <div class="job-info">
        <div class="job-name">${escapeHtml(job.original_name)}</div>
        <div class="job-meta">
          <span class="tag orange">${escapeHtml(job.info.filament_type)}</span>
          ${job.info.nozzle_diameter > 0 ? `<span class="tag cyan" title="Nozzle diameter">⌀ ${job.info.nozzle_diameter}mm</span>` : ''}
          ${job.info.nozzle_flow_type ? `<span class="tag purple" title="Flow type">${escapeHtml(job.info.nozzle_flow_type === 'High Flow' ? 'HF' : job.info.nozzle_flow_type)}</span>` : ''}
          ${job.info.nozzle_hrc ? `<span class="tag purple" title="Nozzle material">${escapeHtml(job.info.nozzle_hrc.replace(' Steel', '').replace(' Carbide', ''))}</span>` : ''}
          <span class="tag cyan">N ${job.info.nozzle_temp}°C</span>
          <span class="tag cyan">B ${job.info.bed_temp}°C</span>
          ${job.info.chamber_temp > 0 ? `<span class="tag yellow">C ${job.info.chamber_temp}°C</span>` : ''}
          ${job.info.max_z_height > 0 ? `<span class="tag yellow">↕ ${job.info.max_z_height.toFixed(1)}mm</span>` : ''}
          <span class="sep">·</span>
          <span>${job.info.body_lines.toLocaleString()} ${currentLang === 'en' ? 'lines' : '라인'}</span>
          <span class="sep">·</span>
          <span>${job.info.size_kb} KB</span>
        </div>
      </div>
      <div class="count-input">
        <button data-act="dec" data-idx="${idx}">−</button>
        <input type="number" min="1" max="999" value="${job.count}" data-idx="${idx}" />
        <button data-act="inc" data-idx="${idx}">+</button>
      </div>
      <button class="btn-icon" data-act="del" data-idx="${idx}" title="${currentLang === 'en' ? 'Delete' : '삭제'}">×</button>
    `;
    jobListEl.appendChild(el);
  });

  // Count / delete handlers
  jobListEl.querySelectorAll('button[data-act], input[data-idx]').forEach(el => {
    if (el.tagName === 'INPUT') {
      el.addEventListener('change', e => {
        const idx = +e.target.dataset.idx;
        const v = Math.max(1, Math.min(999, parseInt(e.target.value) || 1));
        state.jobs[idx].count = v;
        e.target.value = v;
        render();
      });
    } else {
      el.addEventListener('click', e => {
        const idx = +e.currentTarget.dataset.idx;
        const act = e.currentTarget.dataset.act;
        if (act === 'inc') state.jobs[idx].count = Math.min(999, state.jobs[idx].count + 1);
        else if (act === 'dec') state.jobs[idx].count = Math.max(1, state.jobs[idx].count - 1);
        else if (act === 'del') {
          const [removed] = state.jobs.splice(idx, 1);
          requestJob('delete_upload', { stored_name: removed.stored_name }).catch(error => {
            if (error.name !== 'AbortError') showToast(error.message, 'error');
          });
        }
        render();
      });
    }
  });

  // Summary
  const totalCopies = state.jobs.reduce((s, j) => s + j.count, 0);
  const totalSize = state.jobs.reduce((s, j) => s + j.info.size_kb * j.count, 0);
  sumJobs.textContent = state.jobs.length;
  sumPrints.textContent = totalCopies;
  sumSize.textContent = totalSize >= 1024 ? (totalSize / 1024).toFixed(1) + ' MB' : totalSize.toFixed(0) + ' KB';
  generateBtn.disabled = !state.jobs.length || Boolean(activeGeneration);

  updateCompatBanner();
  refreshSweepViz();
}

// ============================================================
// Multi-project compatibility check (persistent banner)
// ============================================================
function checkCompatibility() {
  // Compare every job to the first → return the list of mismatched jobs + reasons
  if (state.jobs.length < 2) return [];
  const first = state.jobs[0].info;
  const issues = [];
  for (let i = 1; i < state.jobs.length; i++) {
    const j = state.jobs[i].info;
    const diffs = [];
    if (first.nozzle_diameter && j.nozzle_diameter &&
        Math.abs(first.nozzle_diameter - j.nozzle_diameter) > 0.001) {
      diffs.push({k: 'nozzle_diameter', a: j.nozzle_diameter + 'mm', b: first.nozzle_diameter + 'mm'});
    }
    if (first.nozzle_temp && j.nozzle_temp &&
        Math.abs(first.nozzle_temp - j.nozzle_temp) > 10) {
      diffs.push({k: 'nozzle_temp', a: j.nozzle_temp + '°C', b: first.nozzle_temp + '°C'});
    }
    if (first.bed_temp && j.bed_temp &&
        Math.abs(first.bed_temp - j.bed_temp) > 5) {
      diffs.push({k: 'bed_temp', a: j.bed_temp + '°C', b: first.bed_temp + '°C'});
    }
    if (first.filament_type && j.filament_type &&
        first.filament_type !== j.filament_type) {
      diffs.push({k: 'filament', a: j.filament_type, b: first.filament_type});
    }
    if (diffs.length > 0) {
      issues.push({job: state.jobs[i], diffs: diffs});
    }
  }
  return issues;
}

function updateCompatBanner() {
  const banner = document.getElementById('compatBanner');
  const issues = checkCompatibility();
  banner.style.display = issues.length ? 'block' : 'none';
  if (!issues.length) return;
  const en = currentLang === 'en';
  const labels = en
    ? {nozzle_diameter:'Nozzle Ø', nozzle_temp:'Nozzle °C', bed_temp:'Bed °C', filament:'Filament'}
    : {nozzle_diameter:'노즐 Ø', nozzle_temp:'노즐 °C', bed_temp:'베드 °C', filament:'필라멘트'};
  document.getElementById('compatBannerTitle').textContent = en ? 'Different print settings' : '파일 간 인쇄 설정 차이';
  document.getElementById('compatBannerBody').textContent = issues.map(({job, diffs}) =>
    job.original_name + ' · ' + diffs.map(d => (labels[d.k] || d.k) + ' ' + d.a + ' / ' + d.b).join(', ')
  ).join('\n');
  document.getElementById('compatBannerBody').style.whiteSpace = 'pre-line';
  document.getElementById('compatBannerHelp').textContent = en
    ? 'The first job supplies the start settings. Re-slice with matching settings or review before generating.'
    : '첫 파일의 시작 설정을 사용합니다. 같은 설정으로 다시 슬라이스하거나 생성 전에 차이를 확인하세요.';
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ============================================================
// Settings-section toggles
// ============================================================
document.querySelectorAll('.settings-header').forEach(h => {
  h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed'));
});

// ============================================================
// Generate
// ============================================================
function collectSettings() {
  const ids = [
    'cooling_bed_temp','cooling_retries','cooling_chamber_temp','part_fan_speed','aux_fan_speed',
    'chamber_fan_speed','cooling_park_z_min','park_z_clearance',
    'eject_method','eject_z_offset','eject_z_start_offset','eject_descent_steps',
    'eject_speed','eject_passes','back_overhang_mm','front_overhang_mm',
    'bed_size_x','bed_size_y','purge_length_mm','post_print_override_min',
  ];
  const s = {};
  ids.forEach(id => { s[id] = document.getElementById(id).value; });
  // Fan values: UI is % (0-100), backend is PWM (0-255). Convert.
  ['part_fan_speed','aux_fan_speed','chamber_fan_speed'].forEach(id => {
    const pct = parseInt(s[id]) || 0;
    s[id] = Math.max(0, Math.min(255, Math.round(pct * 255 / 100)));
  });
  ['part_fan_enabled','aux_fan_enabled','chamber_fan_enabled',
   'verify_build_plate','pause_after_eject','nozzle_clean_between',
   'rehome_xy_between','rehome_z_between','purge_between'].forEach(id => {
    s[id] = document.getElementById(id).checked;
  });
  // Sound presets (6 events)
  ['sound_print_start','sound_print_done','sound_cool_done',
   'sound_sweep_done','sound_restart','sound_print_end'].forEach(id => {
    const el = document.getElementById(id);
    if (el) s[id] = el.value;
  });
  // Custom melodies — send everything from localStorage
  s.custom_melodies = getCustomMelodies();
  // Locale — G-code comment language
  s.lang = currentLang;
  return s;
}

// ============================================================
// Dry-run modal + generate handler
// ============================================================
const drModal = document.getElementById('dryRunModal');

function dryRunHeight() {
  if (!state.jobs.length) return 40;
  const heights = state.jobs.map(job => job.info.max_z_height);
  return heights.every(h => Number.isFinite(h) && h > 0)
    ? heights.reduce((highest, h) => Math.max(highest, h), 0) : null;
}

function readWarningMargin() {
  const input = document.getElementById('safetyMargin');
  if (!input.reportValidity()) return null;
  return input.value === '' ? 0 : input.valueAsNumber;
}

function openDryRunModal() {
  // Refresh the modal info panel (based on the uploaded file)
  const sampleStored = state.jobs.length > 0 ? state.jobs[0].stored_name : null;
  const simHeight = dryRunHeight();
  const simNozzle = state.jobs.length > 0 ? (state.jobs[0].info.nozzle_temp || 220) : 220;
  const simBed = state.jobs.length > 0 ? (state.jobs[0].info.bed_temp || 55) : 55;

  document.getElementById('drInfoH').textContent = simHeight ?? '—';
  document.getElementById('drInfoN').textContent = simNozzle;
  document.getElementById('drInfoB').textContent = simBed;
  document.getElementById('drInfoSample').textContent = sampleStored
    ? tValue({ko:'시작 G-code · ', en:'Start G-code · '}) + state.jobs[0].original_name
    : tValue({ko:'기본 시작 동작 · 가상 높이 40 mm', en:'Default start sequence · simulated height 40 mm'});
  document.getElementById('drInfoSample').style.color = sampleStored
    ? 'var(--green)' : 'var(--yellow)';

  drModal.style.display = 'flex';
}

function closeDryRunModal() {
  drModal.style.display = 'none';
}

document.getElementById('dryRunBtn').addEventListener('click', openDryRunModal);
document.getElementById('drCancel').addEventListener('click', closeDryRunModal);
document.getElementById('drCancel2').addEventListener('click', closeDryRunModal);
drModal.addEventListener('click', (e) => {
  if (e.target === drModal) closeDryRunModal();
});

async function showClearanceError(response, data) {
  if (response.status !== 409 || !['z_collision_bottom_mode', 'z_collision_step_drop', 'z_collision_unknown_height'].includes(data.error)) return false;
  await showAlertModal(tValue(data.title), escapeHtml(tValue(data.message)).replace(/\n/g, '<br>'));
  return true;
}

document.getElementById('drGenerate').addEventListener('click', async () => {
  const warningMargin = readWarningMargin();
  if (warningMargin === null) { closeDryRunModal(); return; }
  const sampleStored = state.jobs.length > 0 ? state.jobs[0].stored_name : null;
  const simHeight = dryRunHeight();
  const simNozzle = state.jobs.length > 0 ? (state.jobs[0].info.nozzle_temp || 220) : 220;
  const simBed = state.jobs.length > 0 ? (state.jobs[0].info.bed_temp || 55) : 55;

  const phases = {
    include_cooling:  document.getElementById('dr_include_cooling').checked,
    wait_for_cooling: document.getElementById('dr_wait_cooling').checked,
    include_eject:    document.getElementById('dr_include_eject').checked,
    include_reheat:   document.getElementById('dr_include_reheat').checked,
    wait_for_reheat:  document.getElementById('dr_wait_reheat').checked,
    include_reset:    document.getElementById('dr_include_reset').checked,
    minimal_start:    document.getElementById('dr_minimal_start').checked,
    skip_ams_load:    document.getElementById('dr_skip_ams_load').checked,
    cycles:           parseInt(document.getElementById('dr_cycles').value || '1', 10),
  };

  const btn = document.getElementById('drGenerate');
  btn.disabled = true;
  btn.textContent = t('generating');
  const revision = clearResult();

  try {
    const res = await requestJob('dry_run', {
      settings: collectSettings(), safety_margin_mm: warningMargin, sample_stored_name: sampleStored,
      simulated_print_height: simHeight, simulated_nozzle_temp: simNozzle,
      simulated_bed_temp: simBed, phases,
    });
    const data = res.data;
    if (revision !== resultRevision) return;
    if (await showClearanceError(res, data)) return;
    if (!res.ok) throw new Error(tValue(data.error));
    displayResult(res, phases.cycles);
    closeDryRunModal();
    tToast({ko: '✓ Dry-run G-code 생성 완료', en: '✓ Dry-run G-code generated'}, 'success');
  } catch (e) {
    if (revision !== resultRevision) return;
    showToast('✗ ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = t('generate_dry');
  }
});

// Fan toggle ↔ speed input linkage (input disabled when OFF)
[['part_fan_enabled','part_fan_speed','fan-row-p1'],
 ['aux_fan_enabled','aux_fan_speed','fan-row-p2'],
 ['chamber_fan_enabled','chamber_fan_speed','fan-row-p3']].forEach(([tog, spd, row]) => {
  const togEl = document.getElementById(tog);
  const spdEl = document.getElementById(spd);
  const rowEl = document.getElementById(row);
  const sync = () => {
    spdEl.disabled = !togEl.checked;
    rowEl.classList.toggle('disabled', !togEl.checked);
  };
  togEl.addEventListener('change', sync);
  sync();
});

generateBtn.addEventListener('click', async () => {
  if (state.jobs.length === 0) return;
  const warningMargin = readWarningMargin();
  if (warningMargin === null) return;

  const sources = new Set(state.jobs.map(j => j.info.source_3mf_stored).filter(Boolean));
  if (sources.size > 1 && state.jobs[0].info.source_3mf_stored) {
    const ok = await showConfirmModal(tValue({ko:'여러 3MF 원본', en:'Multiple 3MF sources'}),
      tValue({ko:'결과 3MF는 첫 파일의 AMS 슬롯을 사용합니다. 다른 파일이 같은 슬롯을 쓰는지 확인하세요.',
              en:'The result uses the first file’s AMS slots. Check that the other files use the same slots.'}));
    if (!ok) return;
  }
  const revision = clearResult();

  activeGeneration = revision;
  generateBtn.disabled = true;
  generateBtn.textContent = tValue({ko:'생성 중…', en:'Generating…'});
  try {
    const payload = {
      jobs: state.jobs.map(j => ({
        stored_name: j.stored_name, original_name: j.original_name, count: j.count,
        source_3mf_stored: j.info.source_3mf_stored || null, source_plate_name: j.info.source_plate_name || null,
      })),
      settings: collectSettings(), safety_margin_mm: warningMargin, want_3mf: true
    };
    let res = await requestJob('generate', payload);
    if (revision !== resultRevision) return;
    let data = res.data;
    if (res.status === 409 && data.error === 'incompatible_jobs') {
      const differences = data.warnings.map(w => escapeHtml(tValue(w))).join('<br>');
      const confirmed = await showConfirmModal(tValue(data.title), differences + '<br><br>' + escapeHtml(tValue({
        ko:'계속하면 첫 파일의 인쇄 설정이 적용됩니다.', en:'Continuing applies the first file’s start settings.'
      })));
      if (!confirmed || revision !== resultRevision) return;
      res = await requestJob('generate', {...payload, force_compatibility: true});
      if (revision !== resultRevision) return;
      data = res.data;
    }

    if (await showClearanceError(res, data)) return;

    if (!res.ok) throw new Error(tValue(data.error, '생성 실패'));

    displayResult(res);
  } catch (e) {
    if (revision !== resultRevision) return;
    showToast('✗ ' + e.message, 'error');
  } finally {
    if (activeGeneration === revision) {
      activeGeneration = 0;
      generateBtn.textContent = t('btn_generate');
      render();
    }
  }
});

// ============================================================
// Init
// ============================================================
document.getElementById('resetBtn').addEventListener('click', async () => {
  const isEN = currentLang === 'en';
  const ok = await showConfirmModal(
    isEN ? 'Reset' : '초기화',
    isEN
      ? 'Clear this tab’s files and result?'
      : '이 탭의 파일 목록과 생성 결과를 비울까요?',
    {okLabel: isEN ? 'Reset' : '초기화'}
  );
  if (!ok) return;
  document.getElementById('safetyMargin').value = 0;
  ++inputVersion;
  activeGeneration = 0;
  clearResult();
  generateBtn.textContent = t('btn_generate');
  state.jobs = [];
  render();
  resetWorker();
  tToast({ko: '초기화 완료', en: 'Reset complete'});
});

// ============================================================
// Load sound presets + persist to localStorage
// ============================================================
const SOUND_EVENTS = ['sound_print_start', 'sound_print_done', 'sound_cool_done',
                       'sound_sweep_done', 'sound_restart', 'sound_print_end'];
const SOUND_DEFAULTS = {
  sound_print_start: '',                  // "" = Bambu 기본값 유지
  sound_print_done: 'do_re_mi',
  sound_cool_done: 'cavalry_short',
  sound_sweep_done: 'victory',
  sound_restart: 'bambu_default_start',
  sound_print_end: '',                    // "" = Bambu 기본값 유지
};
// Start / end events allow the "keep factory" option (value = "")
const SOUND_ALLOW_DEFAULT = new Set(['sound_print_start', 'sound_print_end']);

let presetRequest;
async function loadSoundPresets() {
  try {
    presetRequest ??= fetch(new URL('./presets.json', import.meta.url)).then(res => {
      if (!res.ok) throw new Error('Could not load sound presets.');
      return res.json();
    }).catch(error => { presetRequest = undefined; throw error; });
    const presets = await presetRequest;
    PRESET_PATTERNS_KEYS = new Set(presets.map(p => p.key));
    // Note cache for preview
    PRESET_NOTES_CACHE = {};
    presets.forEach(p => { PRESET_NOTES_CACHE[p.key] = p.notes; });

    const customMelodies = getCustomMelodies();
    const customEntries = Object.entries(customMelodies).map(([name, notes]) => ({
      key: name,
      desc: currentLang === 'en'
        ? `(custom) ${notes.length} notes / ${(notes.reduce((s,[_,d])=>s+d,0)/100).toFixed(1)}s`
        : `(커스텀) ${notes.length}음 / ${(notes.reduce((s,[_,d])=>s+d,0)/100).toFixed(1)}초`,
      isCustom: true,
    }));

    SOUND_EVENTS.forEach(evKey => {
      const sel = document.getElementById(evKey);
      if (!sel) return;
      const prevValue = sel.value;
      sel.innerHTML = '';

      // Start/end events: add the "keep Bambu factory default" option (value = "")
      if (SOUND_ALLOW_DEFAULT.has(evKey)) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = currentLang === 'en' ? '🔇 (Keep Bambu Default)' : '🔇 (Bambu 기본값 유지)';
        sel.appendChild(opt);
      }

      // Built-in presets
      presets.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.key;
        // desc may be a {ko, en} dict or a plain string
        const descText = (typeof p.desc === 'object' && p.desc !== null)
                          ? (p.desc[currentLang] || p.desc.ko || '')
                          : (p.desc || '');
        opt.textContent = `${p.key} — ${descText}`;
        sel.appendChild(opt);
      });

      // Custom melodies (★ marker)
      if (customEntries.length > 0) {
        const sep = document.createElement('option');
        sep.disabled = true;
        sep.textContent = currentLang === 'en' ? '── My Custom Melodies ──' : '── 내 커스텀 멜로디 ──';
        sel.appendChild(sep);
        customEntries.forEach(c => {
          const opt = document.createElement('option');
          opt.value = c.key;
          opt.textContent = `★ ${c.key} — ${c.desc}`;
          sel.appendChild(opt);
        });
      }

      // Restore prior value, fall back to localStorage, then default
      // ★ prevValue may be an empty string (sel.value == '' on first load).
      //    In that case the user did NOT intentionally clear it, so fall through to the default.
      // ★ localStorage keys use the 'bambuloop_' namespace (migrated from the previous farmloop_)
      const saved = localStorage.getItem('bambuloop_' + evKey);
      let target;
      if (prevValue) {
        target = prevValue;   // 사용자가 이미 선택한 값 (유효한 문자열)
      } else if (saved !== null) {
        target = saved;       // localStorage에 저장된 값 (빈 문자열 허용)
      } else {
        target = SOUND_DEFAULTS[evKey];  // 하드코딩 기본값
      }
      if ([...sel.options].some(o => o.value === target && !o.disabled)) {
        sel.value = target;
      }

      // Persist on change
      sel.onchange = () => localStorage.setItem('bambuloop_' + evKey, sel.value);
    });

    // Show the catalog count
    const countEl = document.getElementById('soundCatalogCount');
    if (countEl) {
      countEl.textContent = currentLang === 'en'
        ? `(Built-in ${presets.length} + Custom ${customEntries.length})`
        : `(기본 ${presets.length} + 커스텀 ${customEntries.length})`;
    }
  } catch (e) {
    console.error('사운드 프리셋 로드 실패:', e);
  }
}

// ============================================================
// Catalog download — sends the mode + custom melodies
// ============================================================
document.getElementById('soundCatalogBtn').addEventListener('click', async () => {
  const btn = document.getElementById('soundCatalogBtn');
  const mode = document.getElementById('catalogMode').value;
  btn.disabled = true;
  btn.textContent = t('generating');
  try {
    const res = await requestJob('sound_catalog', {mode, lang: currentLang, custom_melodies: getCustomMelodies()});
    const data = res.data;
    if (!res.ok) throw new Error(tValue(data.error));
    triggerDownload(res.blob, data.filename);
    tToast({ko: `✓ 카탈로그 다운로드 (${data.item_count}개, ${data.size_kb}KB)`, en: `✓ Catalog downloaded (${data.item_count} items, ${data.size_kb}KB)`}, 'success');
  } catch (e) {
    showToast('✗ ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = t('btn_catalog');
  }
});

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ============================================================
// Custom melody builder
// ============================================================
const CUSTOM_KEY = 'farmloop_custom_melodies';
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

let cmCurrentNotes = [];  // [[midi, dur], ...]
let cmEditingName = null;  // 기존 멜로디 편집 중이면 이름

function getCustomMelodies() {
  try { return Object.assign(Object.create(null), JSON.parse(localStorage.getItem(CUSTOM_KEY) || '{}')); }
  catch { return {}; }
}
function setCustomMelodies(obj) {
  localStorage.setItem(CUSTOM_KEY, JSON.stringify(obj));
}

// Build the piano keyboard in place of a pitch dropdown
const PIANO_WHITE_NOTES = [60,62,64,65,67,69,71, 72,74,76,77,79,81,83, 84,86];
const PIANO_BLACK_NOTES = [
  {midi: 61, after: 0},  // C#4
  {midi: 63, after: 1},  // D#4
  {midi: 66, after: 3},  // F#4
  {midi: 68, after: 4},  // G#4
  {midi: 70, after: 5},  // A#4
  {midi: 73, after: 7},  // C#5
  {midi: 75, after: 8},  // D#5
  {midi: 78, after: 10}, // F#5
  {midi: 80, after: 11}, // G#5
  {midi: 82, after: 12}, // A#5
  {midi: 85, after: 14}, // C#6
];
const NOTE_NAMES_FLAT = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
function midiToName(midi) {
  return NOTE_NAMES_FLAT[midi % 12] + (Math.floor(midi/12) - 1);
}

function buildPianoUI() {
  const container = document.getElementById('pianoContainer');
  if (!container || container.dataset.built === 'yes') return;
  container.dataset.built = 'yes';

  const W = 30; // 흰건반 너비 (CSS와 동일)
  const BW = 20; // 검은건반 너비

  // White-keys row
  const whiteRow = document.createElement('div');
  whiteRow.className = 'piano-white-row';
  PIANO_WHITE_NOTES.forEach(midi => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'piano-key piano-white' + (midi % 12 === 0 ? ' octave-c' : '');
    btn.dataset.midi = midi;
    btn.title = midiToName(midi) + ` (MIDI ${midi})`;
    const label = document.createElement('span');
    label.className = 'key-label';
    label.textContent = midiToName(midi);
    btn.appendChild(label);
    btn.addEventListener('click', () => onPianoKey(midi, btn));
    whiteRow.appendChild(btn);
  });
  container.appendChild(whiteRow);

  // Black keys (absolute-positioned)
  PIANO_BLACK_NOTES.forEach(({midi, after}) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'piano-key piano-black';
    btn.dataset.midi = midi;
    btn.title = midiToName(midi) + ` (MIDI ${midi})`;
    btn.style.left = ((after + 1) * (W + 1) - BW/2) + 'px';
    const label = document.createElement('span');
    label.className = 'key-label';
    label.textContent = midiToName(midi);
    btn.appendChild(label);
    btn.addEventListener('click', () => onPianoKey(midi, btn));
    container.appendChild(btn);
  });
}

function onPianoKey(midi, btnEl) {
  const dur = parseInt(document.getElementById('cmDuration').value);
  cmCurrentNotes.push([midi, dur]);
  // Instant in-browser preview (single tone)
  playSingleNote(midi, dur);
  renderCmNoteList();
  // Visual feedback
  btnEl.classList.add('flash');
  setTimeout(() => btnEl.classList.remove('flash'), Math.max(120, dur * 10));
}

function playSingleNote(midi, durTicks) {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const sec = durTicks / 100;
  const freq = 440 * Math.pow(2, (midi - 69) / 12);
  const t = audioCtx.currentTime;
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.type = 'sine';
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0, t);
  gain.gain.linearRampToValueAtTime(0.25, t + 0.01);
  gain.gain.linearRampToValueAtTime(0.25, t + sec - 0.02);
  gain.gain.linearRampToValueAtTime(0, t + sec);
  osc.connect(gain).connect(audioCtx.destination);
  osc.start(t);
  osc.stop(t + sec);
}

// Duration slider display
const cmDur = document.getElementById('cmDuration');
cmDur.addEventListener('input', () => {
  document.getElementById('cmDurDisplay').textContent = (cmDur.value / 100).toFixed(2) + (currentLang === 'en' ? 's' : '초');
  document.getElementById('cmDurTicks').textContent = cmDur.value;
});

// Add a rest
document.getElementById('cmAddRest').addEventListener('click', () => {
  cmCurrentNotes.push([0, parseInt(cmDur.value)]);
  renderCmNoteList();
});

function renderCmNoteList() {
  const listEl = document.getElementById('cmNoteList');
  const emptyEl = document.getElementById('cmEmptyHint');
  listEl.innerHTML = '';
  if (cmCurrentNotes.length === 0) {
    emptyEl.style.display = 'block';
  } else {
    emptyEl.style.display = 'none';
    cmCurrentNotes.forEach(([midi, dur], idx) => {
      const tag = document.createElement('div');
      tag.style.cssText = 'background:var(--bg-2); border:1px solid var(--line-2); padding:5px 8px; font-size:11px; display:flex; gap:6px; align-items:center;';
      const label = midi === 0 ? '— rest' : (NOTE_NAMES[midi % 12] + (Math.floor(midi/12) - 1));
      tag.innerHTML = `
        <span style="color:${midi === 0 ? 'var(--text-faint)' : 'var(--text)'}; min-width:42px;">${label}</span>
        <span style="color:var(--text-dim);">${(dur/100).toFixed(2)}s</span>
        <button data-act="up" data-i="${idx}" style="background:none; border:1px solid var(--line); color:var(--text); cursor:pointer; padding:1px 5px;">↑</button>
        <button data-act="dn" data-i="${idx}" style="background:none; border:1px solid var(--line); color:var(--text); cursor:pointer; padding:1px 5px;">↓</button>
        <button data-act="rm" data-i="${idx}" style="background:none; border:1px solid var(--line); color:var(--accent); cursor:pointer; padding:1px 5px;">×</button>
      `;
      listEl.appendChild(tag);
    });
    listEl.querySelectorAll('button').forEach(b => {
      b.addEventListener('click', () => {
        const i = parseInt(b.dataset.i);
        if (b.dataset.act === 'up' && i > 0) {
          [cmCurrentNotes[i-1], cmCurrentNotes[i]] = [cmCurrentNotes[i], cmCurrentNotes[i-1]];
        } else if (b.dataset.act === 'dn' && i < cmCurrentNotes.length - 1) {
          [cmCurrentNotes[i], cmCurrentNotes[i+1]] = [cmCurrentNotes[i+1], cmCurrentNotes[i]];
        } else if (b.dataset.act === 'rm') {
          cmCurrentNotes.splice(i, 1);
        }
        renderCmNoteList();
      });
    });
  }
  document.getElementById('cmNoteCount').textContent = cmCurrentNotes.length;
  const totalTicks = cmCurrentNotes.reduce((s, [_, d]) => s + d, 0);
  const secStr = (totalTicks / 100).toFixed(1);
  document.getElementById('cmTotalDur').textContent = currentLang === 'en' ? `${secStr}s` : `${secStr}초`;
  // Refresh the label prefix ("N notes")
  const countEl = document.getElementById('cmNoteCount');
  if (countEl && countEl.parentElement) {
    const span = countEl.parentElement.querySelector('.cm-notes-suffix');
    if (span) span.textContent = currentLang === 'en' ? ' notes, ' : '음, ';
  }
}

// Browser preview (Web Audio API)
let audioCtx = null;
document.getElementById('cmPreviewBrowser').addEventListener('click', () => {
  if (cmCurrentNotes.length === 0) { tToast({ko: '음을 먼저 추가하세요', en: 'Add a note first'}, 'error'); return; }
  playMelodyInBrowser(cmCurrentNotes);
  const totalSec = cmCurrentNotes.reduce((s, [_, d]) => s + d, 0) / 100;
  tToast({ko: `🔊 브라우저 재생 (${totalSec.toFixed(1)}초)`, en: `🔊 Browser playback (${totalSec.toFixed(1)}s)`}, 'success');
});

// Printer preview (G-code download)
document.getElementById('cmPreviewPrinter').addEventListener('click', async () => {
  if (cmCurrentNotes.length === 0) { tToast({ko: '음을 먼저 추가하세요', en: 'Add a note first'}, 'error'); return; }
  try {
    const res = await requestJob('sound_catalog', {single_notes: cmCurrentNotes, lang: currentLang});
    const data = res.data;
    if (!res.ok) throw new Error(tValue(data.error));
    triggerDownload(res.blob, data.filename);
    tToast({ko: '✓ 프린터 미리듣기 G-code 다운로드', en: '✓ Printer preview G-code downloaded'}, 'success');
  } catch (e) { showToast('✗ ' + e.message, 'error'); }
});

// Save (auto-clears after save → endless-add workflow)
document.getElementById('cmSave').addEventListener('click', async () => {
  const name = document.getElementById('cmName').value.trim();
  if (!name) { tToast({ko: '이름을 입력하세요', en: 'Enter a name'}, 'error'); return; }
  if (cmCurrentNotes.length === 0) { tToast({ko: '음을 추가하세요', en: 'Add at least one note'}, 'error'); return; }
  if (PRESET_PATTERNS_KEYS.has(name)) {
    tToast({ko: '내장 프리셋과 같은 이름은 사용 불가', en: 'Cannot use the same name as a built-in preset'}, 'error'); return;
  }
  const all = getCustomMelodies();
  if (all[name] && cmEditingName !== name) {
    const isEN = currentLang === 'en';
    const ok = await showConfirmModal(
      isEN ? 'Overwrite?' : '덮어쓰기?',
      isEN ? `Overwrite existing melody '<strong>${escapeHtml(name)}</strong>'?` : `<strong>'${escapeHtml(name)}'</strong> 멜로디를 덮어쓸까요?`,
      {okLabel: isEN ? 'Overwrite' : '덮어쓰기'}
    );
    if (!ok) return;
  }
  if (cmEditingName && cmEditingName !== name) delete all[cmEditingName];
  all[name] = cmCurrentNotes.slice();
  setCustomMelodies(all);
  tToast({ko: `✓ '${name}' 저장됨 (총 ${Object.keys(all).length}개)`, en: `✓ '${name}' saved (total ${Object.keys(all).length})`}, 'success');

  // ★ Auto-clear — ready for the next melody
  cmCurrentNotes = [];
  cmEditingName = null;
  document.getElementById('cmName').value = suggestNextName();
  renderCmNoteList();
  renderCmSavedList();
  loadSoundPresets();
});

function suggestNextName() {
  // Pick the localized "My Melody N" label based on currentLang
  const all = getCustomMelodies();
  const prefix = currentLang === 'en' ? 'My Melody ' : '내 멜로디 ';
  let n = 1;
  while (all[prefix + n]) n++;
  return prefix + n;
}

// New-melody button
document.getElementById('cmClear').addEventListener('click', async () => {
  if (cmCurrentNotes.length > 0) {
    const isEN = currentLang === 'en';
    const ok = await showConfirmModal(
      isEN ? 'Clear current work?' : '현재 작업 비우기?',
      isEN ? 'Clear the current melody being edited? (Unsaved changes will be lost.)'
           : '현재 작업 중인 멜로디를 비울까요? (저장하지 않은 변경사항은 사라집니다)',
      {okLabel: isEN ? 'Clear' : '비우기'}
    );
    if (!ok) return;
  }
  cmCurrentNotes = [];
  cmEditingName = null;
  document.getElementById('cmName').value = suggestNextName();
  renderCmNoteList();
});

function renderCmSavedList() {
  const all = getCustomMelodies();
  const listEl = document.getElementById('cmSavedList');
  const emptyEl = document.getElementById('cmSavedEmpty');
  const countEl = document.getElementById('cmSavedCount');
  listEl.innerHTML = '';
  const names = Object.keys(all);
  if (countEl) countEl.textContent = names.length;
  if (names.length === 0) {
    emptyEl.style.display = 'block';
  } else {
    emptyEl.style.display = 'none';
    names.forEach(name => {
      const notes = all[name];
      const totalSec = (notes.reduce((s, [_, d]) => s + d, 0) / 100).toFixed(1);
      const notesLabel = currentLang === 'en'
        ? `${notes.length} notes / ${totalSec}s`
        : `${notes.length}음 / ${totalSec}초`;
      const editLabel = currentLang === 'en' ? 'Edit' : '편집';
      const delLabel = currentLang === 'en' ? 'Delete' : '삭제';
      const row = document.createElement('div');
      row.style.cssText = 'display:flex; gap:6px; align-items:center; padding:6px 8px; background:var(--bg-2); border:1px solid var(--line);';
      row.innerHTML = `
        <span style="flex:1; font-size:12px; color:var(--text);" class="melody-name"></span>
        <span style="font-size:11px; color:var(--text-dim);">${notesLabel}</span>
        <button data-act="preview" style="background:none; border:1px solid var(--line); color:var(--text); padding:3px 8px; font-size:11px; cursor:pointer;">▶</button>
        <button data-act="edit" style="background:none; border:1px solid var(--line); color:var(--text); padding:3px 8px; font-size:11px; cursor:pointer;">${editLabel}</button>
        <button data-act="del" style="background:none; border:1px solid var(--line); color:var(--accent); padding:3px 8px; font-size:11px; cursor:pointer;">${delLabel}</button>
      `;
      row.querySelector('.melody-name').textContent = name;
      row.querySelector('[data-act=preview]').addEventListener('click', () => {
        playMelodyInBrowser(notes);
      });
      row.querySelector('[data-act=edit]').addEventListener('click', () => {
        cmCurrentNotes = notes.slice();
        cmEditingName = name;
        document.getElementById('cmName').value = name;
        renderCmNoteList();
      });
      row.querySelector('[data-act=del]').addEventListener('click', async () => {
        const isEN = currentLang === 'en';
        const ok = await showConfirmModal(
          isEN ? 'Delete melody?' : '멜로디 삭제?',
          isEN ? `Delete melody '<strong>${escapeHtml(name)}</strong>'?` : `<strong>'${escapeHtml(name)}'</strong> 멜로디를 삭제할까요?`,
          {okLabel: isEN ? 'Delete' : '삭제'}
        );
        if (!ok) return;
        const cur = getCustomMelodies();
        delete cur[name];
        setCustomMelodies(cur);
        if (cmEditingName === name) {
          cmEditingName = null;
          document.getElementById('cmName').value = '';
        }
        renderCmSavedList();
        loadSoundPresets();
      });
      listEl.appendChild(row);
    });
  }
}

// Web Audio playback helper (also used for previewing saved melodies)
function playMelodyInBrowser(notes) {
  if (!notes || notes.length === 0) return;
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  let t = audioCtx.currentTime;
  notes.forEach(([midi, dur]) => {
    const sec = dur / 100;
    if (midi !== 0) {
      const freq = 440 * Math.pow(2, (midi - 69) / 12);
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.25, t + 0.01);
      gain.gain.linearRampToValueAtTime(0.25, t + sec - 0.02);
      gain.gain.linearRampToValueAtTime(0, t + sec);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(t);
      osc.stop(t + sec);
    }
    t += sec;
  });
}

// Modal open/close
const cmModal = document.getElementById('customMelodyModal');
document.getElementById('customMelodyBtn').addEventListener('click', () => {
  cmModal.style.display = 'flex';
  buildPianoUI();  // 첫 열 때만 피아노 빌드
  // Start from empty state (does not carry over previous work)
  if (cmCurrentNotes.length === 0 && !document.getElementById('cmName').value) {
    document.getElementById('cmName').value = suggestNextName();
  }
  renderCmNoteList();
  renderCmSavedList();
});
document.getElementById('cmCancel').addEventListener('click', () => {
  cmModal.style.display = 'none';
});

// ============================================================
// Safety validation UI
// ============================================================
let PRESET_PATTERNS_KEYS = new Set();
let PRESET_NOTES_CACHE = {};   // {presetKey: [[midi, dur], ...]}
let lastSafetyData = null;
let lastSafetyFile = null;
let resultRevision = 0;

let currentResult = null;

function clearResult() {
  if (currentResult) URL.revokeObjectURL(currentResult.url);
  currentResult = null;
  document.getElementById('downloadLink').removeAttribute('href');
  renderSafety(null, null);
  document.getElementById('result').classList.remove('show');
  return ++resultRevision;
}

function resultLabels() {
  if (!currentResult) return;
  const { data, cycles, filename } = currentResult;
  document.getElementById('rCopies').textContent = cycles
    ? tValue({ko: `드라이런 ${cycles}회`, en: `Dry-run ×${cycles}`}) : String(data.total_copies);
  const modes = {
    once: {ko:'원본 검사 1회 포함', en:'One source check'},
    off: {ko:'검사 생략', en:'Check omitted'},
    absent: {ko:'원본 검사 없음', en:'No source check'},
  };
  document.getElementById('resultPlateCheck').textContent =
    [data.plate_target, data.bed_type, tValue(modes[data.plate_check])].filter(Boolean).join(' · ');
  const link = document.getElementById('downloadLink');
  const extension = filename.toLowerCase().endsWith('.3mf') ? '.GCODE.3MF' : '.GCODE';
  link.textContent = t('btn_download').replace('{ext}', extension);
  const note = document.getElementById('repackNote');
  note.hidden = !data.repack_error;
  note.textContent = tValue(data.repack_error);
}

function displayResult({data, blob}, cycles = 0) {
  const filename = data.filename_3mf || data.filename;
  const url = URL.createObjectURL(blob);
  currentResult = {data, blob, filename, url, cycles};
  document.getElementById('rFile').textContent = filename;
  document.getElementById('rSize').textContent = (data.size_kb_3mf ?? data.size_kb) + ' KB';
  document.getElementById('rLines').textContent = data.lines.toLocaleString();
  const link = document.getElementById('downloadLink');
  link.href = url;
  link.download = filename;
  resultLabels();
  document.getElementById('result').classList.add('show');
  renderSafety(data.safety, filename);
}

const safetyGroups = {
  expected: {count: 'expected_count', moves: 'expected_moves', color: 'var(--text-dim)',
    desc: {ko: '확인된 보정·퍼징·분리 경로에서 출력 영역을 벗어난 이동입니다.', en: 'Off-bed moves on a recognised calibration, purge or eject path.'}},
  soft: {count: 'soft_count', moves: 'soft_violations', color: '#f5a623',
    desc: {ko: '일반 이동이 출력 영역을 벗어났습니다. 해당 줄의 좌표와 경로를 확인하세요.', en: 'An ordinary move leaves the printable area. Check its coordinates and path.'}},
  hard: {count: 'hard_count', moves: 'hard_violations', color: '#e74c3c',
    desc: {ko: '검사 범위를 벗어났거나 동작 순서에서 충돌 위험이 발견됐습니다.', en: 'A move exceeds the checked limits or the command sequence poses a collision risk.'}},
};

function renderSafety(safety, filename) {
  const box = document.getElementById('safetyBox');
  if (!box) return;
  lastSafetyFile = filename || null;
  // A cached engine from before the three groups reported recognised moves as soft.
  if (safety && !safety.error && safety.expected_count === undefined && safety.soft_count !== undefined) {
    safety = {...safety, expected_count: safety.soft_count, expected_moves: safety.soft_violations,
      soft_count: 0, soft_violations: [], verdict: safety.verdict === 'soft_only' ? 'expected_only' : safety.verdict};
  }
  lastSafetyData = filename ? (safety || {error: true}) : null;
  box.style.display = filename ? 'block' : 'none';
  if (!filename) return;
  for (const [kind, group] of Object.entries(safetyGroups)) {
    const card = box.querySelector('[data-safety-group="' + kind + '"]');
    const count = safety?.[group.count];
    card.querySelector('strong').textContent = count ?? '—';
    card.querySelector('button').disabled = !count || !safety[group.moves]?.length;
  }
  if (!safety || safety.error) {
    box.style.borderColor = '#f5a623';
    box.style.background = 'rgba(245,166,35,0.06)';
    document.getElementById('safetyVerdict').textContent = tValue({
      ko: '검증 실패 · 이 파일을 다시 검증하세요', en: 'Validation failed. Recheck this file.'
    });
    for (const id of ['sMoves','sBbox','sPrintable','sPhysical']) {
      document.getElementById(id).textContent = '—';
    }
    document.getElementById('sHeader').textContent = typeof safety?.error === 'string' ? safety.error : '';
    return;
  }

  // verdict badge + box colour
  const verdictEl = document.getElementById('safetyVerdict');
  const passed = safety.verdict === 'safe' || safety.verdict === 'expected_only';
  verdictEl.textContent = passed ? t('safety_ok') : tValue(safety.verdict_label);
  const colorMap = {
    'safe':      { border: '#2ecc71', bg: 'rgba(46,204,113,0.06)' },
    'unverified': { border: 'var(--text-dim)', bg: 'var(--bg-2)' },
    'soft_only': { border: '#f5a623', bg: 'rgba(245,166,35,0.06)' },
    'unsafe':    { border: '#e74c3c', bg: 'rgba(231,76,60,0.08)' },
  };
  const c = colorMap[passed ? 'safe' : safety.verdict] || colorMap['soft_only'];
  box.style.borderColor = c.border;
  box.style.background = c.bg;

  // Stats
  document.getElementById('sMoves').textContent =
    `${safety.total_moves.toLocaleString()} (G0/G1 ${safety.moves_g0g1.toLocaleString()}, G2/G3 ${safety.moves_arc.toLocaleString()})`;
  if (safety.bbox_min && safety.bbox_max) {
    const fmt = a => a.map(v => v.toFixed(1)).join(', ');
    document.getElementById('sBbox').textContent =
      `[${fmt(safety.bbox_min)}] ~ [${fmt(safety.bbox_max)}]`;
  } else {
    document.getElementById('sBbox').textContent = safety.total_moves
      ? tValue({ko:'3축 좌표 미확정', en:'3D bounds unavailable'})
      : tValue({ko:'(이동 없음)', en:'(no moves)'});
  }
  const p = safety.printable, warning = safety.warning_bounds;
  document.getElementById('sPrintable').textContent =
    `X[${p.x_min},${p.x_max}] Y[${p.y_min},${p.y_max}] Z[${p.z_min},${p.z_max}]`;
  document.getElementById('sPhysical').textContent = warning
    ? `X[${warning.x_min},${warning.x_max}] Y[${warning.y_min},${warning.y_max}] Z[${warning.z_min},${warning.z_max}] (${t('warning_margin')} ${safety.margin_mm} mm)` : '—';

  const info = [tValue(safety.header_note)];
  if (safety.source?.includes('!')) info.push(safety.source.slice(safety.source.lastIndexOf('!') + 1));
  if (safety.skipped_moves) info.push(tValue({ko: '미확인 이동', en: 'Incomplete moves'}) + ' ' + safety.skipped_moves);
  document.getElementById('sHeader').textContent = info.join(' · ');
}

// Re-validate (margin changed)
document.getElementById('safetyRecheck').addEventListener('click', async () => {
  if (!lastSafetyFile) { tToast({ko: '먼저 G-code를 생성하세요', en: 'Generate G-code first'}, 'error'); return; }
  const margin = readWarningMargin();
  if (margin === null) return;
  const filename = lastSafetyFile;
  const btn = document.getElementById('safetyRecheck');
  btn.disabled = true;
  btn.textContent = t('checking');
  try {
    const res = await requestJob('validate', {filename, margin_mm: margin, plate_name: currentResult.data.plate_target}, {file: currentResult.blob});
    const data = res.data;
    if (filename !== lastSafetyFile) return;
    if (!res.ok) throw new Error(tValue(data.error));
    renderSafety(data, filename);
    tToast({ko: `✓ 마진 ${margin}mm 재검증 완료`, en: `✓ Re-validated with ${margin}mm margin`}, 'success');
  } catch (e) {
    if (filename === lastSafetyFile) renderSafety({error: e.message}, filename);
  } finally {
    btn.disabled = false;
    btn.textContent = t('safety_recheck');
  }
});

// Violation detail modal
function showViolationsModal(kind) {
  if (!lastSafetyData || lastSafetyData.error) return;
  const group = safetyGroups[kind];
  const list = lastSafetyData[group.moves];
  const title = t('safety_' + kind);
  const desc = tValue(group.desc);

  const rows = list.map(v => `
    <tr>
      <td style="padding:6px; border-bottom:1px solid var(--line); color:var(--text-dim); font-family:monospace; font-size:11px;">L${v.line_no}</td>
      <td style="padding:6px; border-bottom:1px solid var(--line); color:${group.color}; font-family:monospace; font-size:11px; word-break:break-all;">${escapeHtml(v.axes.join(', '))}</td>
      <td style="padding:6px; border-bottom:1px solid var(--line); color:var(--text); font-family:monospace; font-size:11px; word-break:break-all;">${escapeHtml(v.command)}</td>
      <td style="padding:6px; border-bottom:1px solid var(--line); color:var(--text-faint); font-size:10px;">${escapeHtml(v.note || '')}</td>
    </tr>
  `).join('');

  // Build the modal dynamically
  let modal = document.getElementById('violationsModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'violationsModal';
    modal.className = 'modal-backdrop';
    document.body.appendChild(modal);
  }
  modal.innerHTML = `
    <div class="modal-card" style="max-width:900px;">
      <div class="modal-header">
        <span style="font-weight:700;">${title}</span>
        <button class="modal-close" onclick="document.getElementById('violationsModal').style.display='none';">×</button>
      </div>
      <div class="modal-body">
        <p style="font-size:12px; color:var(--text-dim); margin-bottom:12px;">${desc}</p>
        <p style="font-size:12px; color:var(--text-dim); margin-bottom:12px;">${tValue({ko:'표시한 이동',en:'Moves shown'})} · <strong>${list.length}</strong></p>
        <div style="max-height:400px; overflow-y:auto; border:1px solid var(--line);">
          <table style="width:100%; border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg-2);">
                <th style="padding:8px; text-align:left; font-size:11px; color:var(--text-dim);">${tValue({ko:'줄',en:'Line'})}</th>
                <th style="padding:8px; text-align:left; font-size:11px; color:var(--text-dim);">${tValue({ko:'위반 축',en:'Axes'})}</th>
                <th style="padding:8px; text-align:left; font-size:11px; color:var(--text-dim);">${tValue({ko:'G-code 명령',en:'Command'})}</th>
                <th style="padding:8px; text-align:left; font-size:11px; color:var(--text-dim);">${tValue({ko:'비고',en:'Notes'})}</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    </div>`;
  modal.style.display = 'flex';
}

for (const card of document.querySelectorAll('[data-safety-group]')) {
  card.querySelector('button').addEventListener('click', () => showViolationsModal(card.dataset.safetyGroup));
}

// Hide the safety box in the result card by default
(function hideSafetyInitially() {
  const box = document.getElementById('safetyBox');
  if (box) box.style.display = 'none';
})();

// Sound preview buttons (▶ next to each event select)
document.querySelectorAll('.sound-preview-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const targetId = btn.dataset.target;
    const sel = document.getElementById(targetId);
    if (!sel || !sel.value) {
      tToast({ko: '선택된 멜로디 없음 (정품 사운드 또는 미선택)', en: 'No melody selected (default sound or unset)'}, 'error');
      return;
    }
    const key = sel.value;
    // Priority: custom melodies → built-in presets
    const customs = getCustomMelodies();
    let notes = customs[key] || PRESET_NOTES_CACHE[key];
    if (!notes || notes.length === 0) {
      tToast({ko: `'${key}' 멜로디를 찾을 수 없음`, en: `Melody '${key}' not found`}, 'error');
      return;
    }
    playMelodyInBrowser(notes);
    tToast({ko: `🔊 '${key}' 재생`, en: `🔊 Playing '${key}'`}, 'success');
  });
});

loadSoundPresets();

// ============================================================
// Sweep visualization (live preview + head animation)
// ============================================================
const sweepViz = {
  svg: null, zbar: null,
  svgW: 360, svgH: 320,
  bedLeft: 30, bedTop: 30, bedW: 300, bedH: 260,
  paused: true,            // ★ 기본 일시정지 (사용자가 ▶ 누르기 전엔 정지)
  speed: 1.0,
  currentZStep: 0,
  totalCycleSec: 5.0,
  virtualSec: 0,           // ★ 누적 가상 시간 (speed 적용된 진행 시간)
  lastTimestamp: 0,        // 마지막 RAF timestamp (실시간)
  rafId: null,
  params: null,
};

function getSweepParams() {
  const value = (id, fallback) => {
    const n = document.getElementById(id).valueAsNumber;
    return Number.isFinite(n) ? n : fallback;
  };
  const method = document.getElementById('eject_method').value;
  return {
    method,
    bedX: value('bed_size_x', 340),
    bedY: value('bed_size_y', 320),
    backOver: value('back_overhang_mm', 15),
    frontOver: value('front_overhang_mm', 5),
    passes: Math.max(1, Math.min(30, parseInt(document.getElementById('eject_passes').value) || 4)),
    steps: Math.max(1, Math.min(Number(document.getElementById('eject_descent_steps').max), parseInt(document.getElementById('eject_descent_steps').value) || 4)),
    height: dryRunHeight(),
    zEnd: value('eject_z_offset', 0.4),
  };
}

// X-pass coordinates (mm) — same logic as gcode_processor.generate_eject_sequence
function computeXPositions(p) {
  const edge = 3;
  if (p.method === 'sweep' || (p.passes === 1 && p.method !== 'zigzag')) return [Math.floor(p.bedX / 2)];
  const segments = p.method === 'zigzag' ? p.passes : p.passes - 1;
  // First build an evenly spaced X-coordinate list (left → right)
  const xLinear = Array.from({length: segments + 1}, (_, i) => {
    const x = edge + (p.bedX - 2 * edge) * i / segments;
    // Match Python's round-to-even rule on half-millimetre ties.
    return x % 1 === 0.5 ? 2 * Math.round(x / 2) : Math.round(x);
  });
  // edge_to_center mode: reorder so edges alternate inward to the centre
  //   [3, 59, 115, 171, 227, 283, 337]
  //   → [3, 337, 59, 283, 115, 227, 171]
  if (p.method === 'edge_to_center' || p.method === 'edge_to_center_bottom') {
    const result = [];
    let left = 0, right = xLinear.length - 1;
    while (left <= right) {
      result.push(xLinear[left]);
      if (left !== right) result.push(xLinear[right]);
      left++;
      right--;
    }
    return result;
  }
  return xLinear;
}

// Convert bed mm → SVG px
function bedToSvg(p, bedX, bedY) {
  const yBackMm = p.bedY + p.backOver;       // 가장 뒤
  const yFrontMm = -p.frontOver;             // 가장 앞
  const totalYRangeMm = yBackMm - yFrontMm;
  return {
    x: sweepViz.bedLeft + (bedX / p.bedX) * sweepViz.bedW,
    // SVG y=0 is the top (bed back). Map yBackMm to sweepViz.bedTop.
    y: sweepViz.bedTop + ((yBackMm - bedY) / totalYRangeMm) * sweepViz.bedH,
  };
}

function renderSweepStaticBackground(p) {
  const svg = document.getElementById('sweepTopSvg');
  if (!svg) return;
  sweepViz.svg = svg;

  const yBackMm = p.bedY + p.backOver;
  const yFrontMm = -p.frontOver;
  // Printable region (0,0) ~ (bedX, bedY)
  const tl = bedToSvg(p, 0, p.bedY);
  const br = bedToSvg(p, p.bedX, 0);

  // Bed area
  const bedRect = `<rect x="${tl.x}" y="${tl.y}" width="${br.x - tl.x}" height="${br.y - tl.y}"
    fill="#1a1f2a" stroke="#3a4555" stroke-width="1"/>`;

  // Bed area label (top-left)
  const bedLabel = `<text x="${tl.x + 4}" y="${tl.y + 14}" fill="#5a6478" font-size="10" font-family="monospace">BED ${p.bedX}×${p.bedY}</text>`;

  // Back / front overhang regions (drawn lightly)
  const backTop = sweepViz.bedTop;
  const backBot = bedToSvg(p, 0, p.bedY).y;
  const frontTop = bedToSvg(p, 0, 0).y;
  const frontBot = sweepViz.bedTop + sweepViz.bedH;
  const backArea = `<rect x="${tl.x}" y="${backTop}" width="${br.x - tl.x}" height="${backBot - backTop}"
    fill="rgba(255,140,40,0.05)" stroke="#3a4555" stroke-dasharray="3,2"/>`;
  const frontArea = `<rect x="${tl.x}" y="${frontTop}" width="${br.x - tl.x}" height="${frontBot - frontTop}"
    fill="rgba(255,140,40,0.05)" stroke="#3a4555" stroke-dasharray="3,2"/>`;
  const isEN = currentLang === 'en';
  const backLabelText = isEN ? `Back +${p.backOver}mm (Y=${yBackMm})` : `베드 후방 +${p.backOver}mm (Y=${yBackMm})`;
  const frontLabelText = isEN ? `Front -${p.frontOver}mm (Y=${yFrontMm}) → part falls off` : `베드 전방 -${p.frontOver}mm (Y=${yFrontMm}) → 인쇄물 낙하`;
  const backLabel = `<text x="${tl.x + 4}" y="${backTop + 12}" fill="#888" font-size="9">${backLabelText}</text>`;
  const frontLabel = `<text x="${tl.x + 4}" y="${frontBot - 4}" fill="#888" font-size="9">${frontLabelText}</text>`;

  // X-pass guide lines (dotted, top to bottom)
  const xPositions = computeXPositions(p);
  const yTop = sweepViz.bedTop;
  const yBottom = sweepViz.bedTop + sweepViz.bedH;
  const passLines = xPositions.map((x, i) => {
    const sx = bedToSvg(p, x, 0).x;
    const color = (i === 0 || i === xPositions.length - 1) ? "#ff7a2f" : "#4a5568";
    return `<line x1="${sx}" y1="${yTop}" x2="${sx}" y2="${yBottom}"
      stroke="${color}" stroke-width="${i === 0 ? 1.5 : 1}" stroke-dasharray="2,3" opacity="0.5"/>
      <text x="${sx}" y="${yBottom + 11}" fill="${color}" font-size="8" text-anchor="middle">X${x}</text>`;
  }).join("");

  // Y-axis label
  const yAxisText = isEN ? 'Y (front ← → back)' : 'Y (앞 ← → 뒤)';
  const yLabel = `<text x="2" y="${(yTop + yBottom) / 2}" fill="#5a6478" font-size="9" transform="rotate(-90 2 ${(yTop+yBottom)/2})">${yAxisText}</text>`;

  // Head-marker placeholder (animation updates its position)
  const headMarker = `<circle id="sweepHead" cx="${tl.x}" cy="${yTop}" r="6"
    fill="#ff7a2f" stroke="#fff" stroke-width="1.5" opacity="0.95"/>`;

  // Path trail (shows the head's motion history)
  const trailPath = `<path id="sweepTrail" d="" stroke="#ff7a2f" stroke-width="1.2" fill="none" opacity="0.5" stroke-linecap="round"/>`;

  // Virtual print box (bed centre) — lets the user inspect the sweep path
  const objSizeMm = 60;  // 가상 60×60mm 인쇄물
  const objCx = p.bedX / 2;
  const objCy = p.bedY / 2;
  const objTL = bedToSvg(p, objCx - objSizeMm/2, objCy + objSizeMm/2);
  const objBR = bedToSvg(p, objCx + objSizeMm/2, objCy - objSizeMm/2);
  const objBox = `<rect x="${objTL.x}" y="${objTL.y}" width="${objBR.x - objTL.x}" height="${objBR.y - objTL.y}"
    fill="rgba(100,180,255,0.15)" stroke="#5fa8d3" stroke-width="1" stroke-dasharray="4,2"/>
    <text x="${(objTL.x + objBR.x)/2}" y="${(objTL.y + objBR.y)/2 + 3}" fill="#5fa8d3" font-size="9" text-anchor="middle" font-family="monospace">${isEN ? 'sample print' : '예시 인쇄물'}</text>`;

  svg.innerHTML = bedRect + backArea + frontArea + bedLabel + backLabel + frontLabel + objBox + passLines + yLabel + trailPath + headMarker;
}

function renderZBar(p, currentStep) {
  const zbar = document.getElementById('sweepZBar');
  if (!zbar) return;
  const w = 32, h = 180;
  const stepH = (h - 8) / p.steps;
  let parts = `<rect x="2" y="2" width="${w-4}" height="${h-4}" fill="none" stroke="#3a4555"/>`;
  for (let i = 0; i < p.steps; i++) {
    const y = 4 + i * stepH;
    const isActive = i === currentStep;
    // Z-fixed modes (bottom_only / edge_to_center_bottom): every step uses z_end
    const isZFixed = (p.method === 'bottom_only' || p.method === 'edge_to_center_bottom');
    const top = Math.min(335, Math.max(5, p.height || 0));
    const zMm = (isZFixed || p.steps === 1) ? p.zEnd : top - (top - p.zEnd) * i / (p.steps - 1);
    parts += `<rect x="4" y="${y}" width="${w-8}" height="${stepH - 2}"
      fill="${isActive ? '#ff7a2f' : '#2a3441'}" stroke="${isActive ? '#fff' : '#3a4555'}"/>`;
    parts += `<text x="${w/2}" y="${y + stepH/2 + 3}" fill="${isActive ? '#fff' : '#888'}" font-size="8"
      text-anchor="middle" font-family="monospace">${p.height === null ? '—' : zMm.toFixed(1)}</text>`;
  }
  zbar.innerHTML = parts;
  document.getElementById('sweepZLabel').textContent = `${currentStep + 1}/${p.steps}`;
}

function buildSweepPath(p) {
  // Return the head path within one layer (= one Z step) as an SVG coordinate sequence
  // [{x, y, label}, ...]
  const xPositions = computeXPositions(p);
  const yBackMm = p.bedY + p.backOver;
  const yFrontMm = -p.frontOver;
  const path = [];
  // Start: first X + Y back
  path.push({...bedToSvg(p, xPositions[0], yBackMm), label: currentLang === 'en' ? 'Enter' : '진입'});
  for (let i = 0; i < xPositions.length; i++) {
    const x = xPositions[i];
    if (i > 0) {
      // Move X (keep Y back)
      path.push({...bedToSvg(p, x, yBackMm), label: `X→${x}`});
    }
    // Sweep: back → front
    path.push({...bedToSvg(p, x, yFrontMm), label: currentLang === 'en' ? `Sweep ${i+1}/${xPositions.length}` : `스윕 ${i+1}/${xPositions.length}`});
    // Return to back unless this was the final pass
    if (i < xPositions.length - 1) {
      path.push({...bedToSvg(p, x, yBackMm), label: currentLang === 'en' ? 'Y return' : 'Y 복귀'});
    }
  }
  return path;
}

function buildZigzagPath(p) {
  // Zigzag: combine the back → front Y move with the X move (diagonal)
  const xPositions = computeXPositions(p);
  const yBackMm = p.bedY + p.backOver;
  const yFrontMm = -p.frontOver;
  const path = [];
  path.push({...bedToSvg(p, xPositions[0], yBackMm), label: currentLang === 'en' ? 'Enter' : '진입'});
  for (let i = 0; i < p.passes; i++) {
    const endY = i % 2 === 0 ? yFrontMm : yBackMm;
    path.push({...bedToSvg(p, xPositions[i+1], endY),
               label: currentLang === 'en' ? `Diagonal ${i+1}` : `대각 ${i+1}`});
  }
  return path;
}

function buildSinglePath(p) {
  // Single sweep: bed centre, one pass only
  const cx = Math.floor(p.bedX / 2);
  const yBackMm = p.bedY + p.backOver;
  const yFrontMm = -p.frontOver;
  return [
    {...bedToSvg(p, cx, yBackMm), label: currentLang === 'en' ? 'Enter' : '진입'},
    {...bedToSvg(p, cx, yFrontMm), label: currentLang === 'en' ? 'Sweep' : '스윕'},
  ];
}

function renderSweepFrame(t) {
  // t: 0~1 (progress within one layer)
  const p = sweepViz.params;
  if (!p || !sweepViz.svg) return;

  let path;
  if (p.method === 'zigzag') path = buildZigzagPath(p);
  else if (p.method === 'sweep') path = buildSinglePath(p);
  else if (p.method === 'none') {
    document.getElementById('sweepHead').setAttribute('opacity', '0');
    document.getElementById('sweepStatus').textContent = currentLang === 'en' ? 'Eject disabled' : '분리 사용 안 함';
    return;
  }
  else path = buildSweepPath(p);

  if (path.length < 2) return;
  // Map t along the total path length
  const totalSegments = path.length - 1;
  const tIdx = t * totalSegments;
  const segIdx = Math.min(Math.floor(tIdx), totalSegments - 1);
  const segT = tIdx - segIdx;
  const a = path[segIdx], b = path[segIdx + 1];
  const cx = a.x + (b.x - a.x) * segT;
  const cy = a.y + (b.y - a.y) * segT;

  // Update head position
  const head = document.getElementById('sweepHead');
  if (head) {
    head.setAttribute('cx', cx);
    head.setAttribute('cy', cy);
    head.setAttribute('opacity', '0.95');
  }

  // Path trail (draw where we have already been)
  const trail = document.getElementById('sweepTrail');
  if (trail) {
    let d = `M ${path[0].x} ${path[0].y}`;
    for (let i = 1; i <= segIdx; i++) d += ` L ${path[i].x} ${path[i].y}`;
    d += ` L ${cx} ${cy}`;
    trail.setAttribute('d', d);
  }

  // Status text
  const label = b.label;
  const zStepLabel = currentLang === 'en' ? `Z ${sweepViz.currentZStep + 1}/${p.steps}` : `Z단 ${sweepViz.currentZStep + 1}/${p.steps}`;
  document.getElementById('sweepStatus').textContent = `${label} · ${zStepLabel}`;
}

function sweepAnimate(timestamp) {
  if (!sweepViz.params) return;
  if (sweepViz.lastTimestamp === 0) sweepViz.lastTimestamp = timestamp;

  // realtime delta × speed = virtual-time increment
  const realDeltaMs = timestamp - sweepViz.lastTimestamp;
  sweepViz.lastTimestamp = timestamp;
  if (!sweepViz.paused) {
    sweepViz.virtualSec += (realDeltaMs / 1000) * sweepViz.speed;
  }

  const cycleSec = sweepViz.totalCycleSec;
  const t = (sweepViz.virtualSec % cycleSec) / cycleSec;

  // When one layer finishes, advance to the next Z step
  const layersDone = Math.floor(sweepViz.virtualSec / cycleSec);
  sweepViz.currentZStep = layersDone % sweepViz.params.steps;

  renderZBar(sweepViz.params, sweepViz.currentZStep);
  renderSweepFrame(t);

  // Keep RAF running even while paused — keeps timestamps fresh and avoids a jump on resume
  // (when paused, virtualSec does not advance — see the if-check above)
  sweepViz.rafId = requestAnimationFrame(sweepAnimate);
}

function startSweepAnim() {
  if (sweepViz.rafId) return;  // 이미 돌고 있음
  sweepViz.lastTimestamp = 0;
  sweepViz.rafId = requestAnimationFrame(sweepAnimate);
}

function stopSweepAnim() {
  if (sweepViz.rafId) {
    cancelAnimationFrame(sweepViz.rafId);
    sweepViz.rafId = null;
  }
}

function refreshSweepViz() {
  sweepViz.params = getSweepParams();
  const height = sweepViz.params.height;
  const label = !state.jobs.length ? tValue({ko:'가상 높이', en:'Sample height'}) : tValue({ko:'최대 높이', en:'Tallest print'});
  document.getElementById('previewHeight').textContent = '· ' + label + ' ' + (height === null ? '—' : height + ' mm');
  sweepViz.currentZStep = Math.min(sweepViz.currentZStep, sweepViz.params.steps - 1);
  renderSweepStaticBackground(sweepViz.params);
  renderZBar(sweepViz.params, sweepViz.currentZStep);
  // Render one frame so the current position shows even while stopped
  if (sweepViz.paused) {
    const cycleSec = sweepViz.totalCycleSec;
    const t = (sweepViz.virtualSec % cycleSec) / cycleSec;
    renderSweepFrame(t);
  }
}

// Control handlers
document.getElementById('sweepPlayBtn').addEventListener('click', () => {
  sweepViz.paused = !sweepViz.paused;
  const btn = document.getElementById('sweepPlayBtn');
  const isEN = currentLang === 'en';
  if (sweepViz.paused) {
    btn.textContent = isEN ? '▶ Play' : '▶ 재생';
    stopSweepAnim();
  } else {
    btn.textContent = isEN ? '⏸ Pause' : '⏸ 일시정지';
    startSweepAnim();
  }
});

document.getElementById('sweepSpeed').addEventListener('input', (e) => {
  // On speed change: virtualSec is preserved (continues from where it was) and ramps at the new speed from the next frame
  sweepViz.speed = parseFloat(e.target.value);
  document.getElementById('sweepSpeedLabel').textContent = sweepViz.speed.toFixed(1) + 'x';
});

document.getElementById('sweepVizToggle').addEventListener('click', () => {
  const content = document.getElementById('sweepVizContent');
  const btn = document.getElementById('sweepVizToggle');
  if (content.style.display === 'none') {
    content.style.display = '';
    btn.textContent = currentLang === 'en' ? 'Collapse ▾' : '접기 ▾';
    refreshSweepViz();
    if (!sweepViz.paused) startSweepAnim();
  } else {
    content.style.display = 'none';
    btn.textContent = currentLang === 'en' ? 'Expand ▸' : '펼치기 ▸';
    stopSweepAnim();
  }
});

// Refresh immediately when related inputs change (animation keeps running)
['eject_method', 'eject_passes', 'eject_descent_steps',
 'back_overhang_mm', 'front_overhang_mm', 'bed_size_x', 'bed_size_y',
 'eject_z_offset', 'eject_z_start_offset'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('input', refreshSweepViz);
});

render();
