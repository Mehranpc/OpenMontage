# گزارش وضعیت مرحلهٔ B — Persian Pipeline V2

**تاریخ گزارش:** `2026-09-06`  
**وضعیت:** جزئی؛ دروازهٔ تأیید انسانی رد نشده است.

## خلاصهٔ اجرایی

یک مسیر V2 اختیاری و نسخه‌دار، یک برش عمودی واقعی و یک مقایسهٔ Legacy/V2 آماده شده است؛ اما این کار «پایان موفق مرحلهٔ B» یا مجوز ادامه به مراحل بعد نیست. بر اساس بخش‌های ۱۵ و ۱۶ مشخصات، پس از دیدن برش واقعی باید برای تأیید انسانی متوقف شد؛ گزارش خروجی نیز `humanVisualApproval: pending` دارد (`projects/persian-v2-stage-b-preview/persian_layout_report.json:61-67`).

بازبینی مستقل، ۵ مورد از ۷ مورد را FAIL کرده است: بلوک V2 هنوز snapshot/اندازه‌گیری/safe-area و placement/motion را مصرف نمی‌کند، برنامهٔ watermark ناقص است، ادعاهای layout اندازه‌گیری‌شده نیستند، و تست مستقل V2 وجود ندارد. بنابراین این preview برای بررسی و تصمیم‌گیری مناسب است، نه برای فعال‌سازی عمومی.

## نسبت با spec و مراحل A–E

- **A — ثبت مبنا و قرارداد:** بخشی از قرارداد نسخه، مسیر Legacy و تغییرات ثبت شده؛ default سراسری تغییر نکرده است.
- **B — برش عمودی قابل دیدن:** دو treatment یعنی `editorial` و `inline-statement`، فونت Estedad، MP4 مقایسه‌ای و گزارش محدودیت‌ها حاضرند. این preview صراحتاً آزمون کوتاه انتقال watermark است (`persian_layout_report.json:68-70`) و خروجی معمول کلیپ کوتاه را تغییر نمی‌دهد.
- **دروازهٔ انسانی بخش ۱۵:** هنوز باز است؛ فریم/MP4 قابل مشاهده‌اند اما تأیید انسانی انجام نشده (`persian_layout_report.json:61-67`).
- **C:** شروع نشده؛ treatmentهای `figure-focus`، `compare`، `build` و `guided-step` تولید/تعمیم داده نشده‌اند (`persian_layout_report.json:68-70`).
- **D:** شروع نشده؛ کنترل جامع هندسه، مطالعه، mask، رگرسیون و گزارش `not_checked` کامل نشده است.
- **E:** شروع نشده؛ V2 default پروژه‌های جدید فعال نشده و Legacy همچنان با نبود `persian.design.version` انتخاب می‌شود (`projects/persian-v2-stage-b-preview/REPRODUCE.txt:9-10`).

## فایل‌های تغییرکرده و دلیل یک‌خطی

- `lib/persian_design.py:7-80` — مرز نسخهٔ V2، snapshot پروفایل، seed و validation محدود Stage B.
- `styles/persian-footage/v2.json` — پروفایل `quiet-editorial` و قرارداد اولیهٔ motion/watermark.
- `remotion-composer/src/persian/v2/PersianV2MomentBlock.tsx:1-19` — renderer اولیهٔ دو treatment V2.
- `remotion-composer/src/persian/types.ts:136-178,275-276` — typeهای presentation، design و watermark plan.
- `remotion-composer/src/persian/PersianFootageVideo.tsx:250-280` — انتخاب صریح Legacy/V2 و اتصال watermark plan.
- `remotion-composer/src/persian/components/PersianWatermarkMark.tsx:91-103` — guard واترمارک خالی و مصرف مسیر plan.
- `tools/video/persian_compose.py:560-605,659-665` — حمل snapshot، ساخت props و برنامهٔ watermark.
- `schemas/artifacts/edit_decisions.schema.json:641-659` — افزودن فیلدهای قرارداد ارائه و اندازهٔ stack.

## پیش‌نمایش‌ها و شواهد

دایرکتوری شواهد: `projects/persian-v2-stage-b-preview/`

- `v2-preview.mp4`: عمودی `1080x1920`، حدود `14.2s`، interval `0.0-14.2s`؛ decode و luminance طبق گزارش پاس شده‌اند (`persian_layout_report.json:11-17,61-63`).
- `legacy-preview.mp4`: خروجی مقایسه‌ای مسیر قدیمی؛ مسیر Legacy با حذف design قابل بازگشت است (`REPRODUCE.txt:9-10`).
- `v2-edit_decisions.json`: ورودی بازتولید V2.
- `persian_layout_report.json`: snapshot/profile hash، seed، دو moment و وضعیت بررسی.
- `events.jsonl` و `REPRODUCE.txt`: رخدادها و دستور بازتولید.

مقایسهٔ محتوایی ثبت‌شده: hook با `editorial`/`soft-reveal` و body با `inline-statement`/`cut-in` (`persian_layout_report.json:19-53`). مقایسهٔ بصری انسانی، contrast و face protection هنوز `not_checked` هستند (`:55-66`).

## نتایج تست و type-check (آخرین اجرا)

- `.venv/bin/python3 -m pytest -q`: **2749 passed, 43 skipped, 3 xfailed, 1 subtests passed** (92.26s).
- تست‌های هدفمند Persian: **264 passed, 1 skipped**.
- `cd remotion-composer && ./node_modules/.bin/tsc --noEmit`: **pass**.
- `git diff --check`: **pass**.
- هر دو preview با `ffprobe` بررسی شدند: **1080x1920، 30fps، 14.250667s**؛ interval ادیت همان `0.0-14.2s` است.

## یافته‌های بازبینی مستقل (a–g)

- **(a) PASS — شاخه‌بندی نسخه:** نبود design مسیر Legacy است و فقط version صریح `2` V2 را فعال می‌کند (`lib/persian_design.py:34-55`; `PersianFootageVideo.tsx:262-268`).
- **(b) PASS — حمل snapshot:** profile version/hash و seed از boundary پایتون به props و composition منتقل می‌شوند (`lib/persian_design.py:45-55`; `tools/video/persian_compose.py:594-595`).
- **(c) FAIL — متن V2 hardcoded است:** اندازه، رنگ، جایگاه و safe-area از snapshot/measurement مصرف نمی‌شوند؛ مقادیر ثابت در `PersianV2MomentBlock` آمده‌اند (`remotion-composer/src/persian/v2/PersianV2MomentBlock.tsx:12-16`).
- **(d) FAIL — placement/motion نادیده گرفته می‌شود:** `presentation.placement` و مقدار motion فقط validate می‌شوند و renderer همیشه top/translateY یکسان دارد (`lib/persian_design.py:57-71`; `PersianV2MomentBlock.tsx:11-16`).
- **(e) FAIL — watermark ناقص است:** vertical و non-vertical candidate یکسان‌اند، `seed` و policy/text-bounds در انتخاب اثر ندارند، و plan با `text_rects=[]` ساخته می‌شود (`lib/persian_design.py:13-32`; `tools/video/persian_compose.py:600-603`). renderer نیز fps را hardcode `30` کرده است (`PersianWatermarkMark.tsx:96-100`).
- **(f) FAIL — ادعای layout اندازه‌گیری نشده:** report می‌گوید bounds «runtime-measured» است، ولی برای V2 bridge در مسیر ساخت stack height اجرا نمی‌شود (`persian_layout_report.json:32-36,49-52`; `tools/video/persian_compose.py:659-665`).
- **(g) FAIL — تست V2 صفر است:** در جست‌وجوی تست در `remotion-composer/src/persian/v2` و مسیر Persian تست مستقلی برای V2 یافت نشد؛ full/targeted اعداد بالا مربوط به verification ثبت‌شده‌اند، نه پوشش V2 اختصاصی.

## محدودیت‌ها و موارد بررسی‌نشده

- `PersianV2MomentBlock` segmentهای با role=`source` را حذف می‌کند (`.../PersianV2MomentBlock.tsx:16`)، پس برابری کامل مدل محتوای Legacy/V2 اثبات نشده است.
- `WatermarkMark` در plan مسیر زمان را با fps ثابت ۳۰ حساب می‌کند (`.../PersianWatermarkMark.tsx:96-100`).
- schema treatment/motionهای C–E را می‌پذیرد، ولی validator پایتون فقط دو treatment و دو motion را قبول می‌کند (`edit_decisions.schema.json:644-647`; `lib/persian_design.py:8-10,57-67`).
- contrast، face protection، بررسی انسانی و کیفیت بصری در report `not_checked`/`pending` هستند.
- رندر مجدد، full test suite، بررسی frame PNGها با چشم، D/E، فعال‌سازی default و regression کامل Legacy در این گزارش انجام نشد.
- guard پیشین watermark حفظ شده است (`PersianWatermarkMark.tsx:91-94`) و مسیر Legacy عمداً تغییر داده نشده است؛ این‌ها جایگزین تأیید بصری نیستند.

## تصمیم‌های نیازمند نظر کاربر

۱. **رفع هر ۵ FAIL** (پیشنهاد): ابتدا snapshot/measurement/safe-area، placement/motion، watermark، گزارش layout و تست‌های V2 اصلاح و سپس preview دوباره بررسی شود.

۲. **محدودکردن دامنهٔ B:** این خروجی صرفاً prototype/transition-test باقی بماند؛ FAILها صریحاً بدهی فنی ثبت شوند و C–E متوقف بمانند.

۳. **توقف کار:** فعال‌سازی V2 و ادامهٔ pipeline انجام نشود؛ Legacy حفظ شود تا تصمیم دیگری ثبت گردد.

## گام‌های بعدی

پس از انتخاب کاربر، گزینهٔ ۱ باید با اولویت اصلاح renderer و اندازه‌گیری واقعی، ساخت plan واترمارک بر اساس bounds/format/seed، همسان‌سازی schema/validator، افزودن تست V2، و سپس render/بازبینی انسانی اجرا شود. تا آن زمان `humanVisualApproval=pending` می‌ماند و هیچ default عمومی تغییر نمی‌کند.

## پیوست: مسیرها و دستورات بازتولید

- Spec: `PERSIAN_PIPELINE_V2_SPEC.md` (local reference; not tracked)، به‌ویژه بخش‌های ۱۵، ۱۶ و ۲۰.
- Preview: `projects/persian-v2-stage-b-preview/` (local project workspace; not tracked).
- بازتولید ثبت‌شده در `REPRODUCE.txt` با `PersianCompose().execute(...)` و خروجی `v2-preview.mp4`.
- بررسی‌های ارزان اجراشده: `git status --short`, `git diff --stat`, `find .../persian-v2-stage-b-preview`, parse کردن `persian_layout_report.json` و جست‌وجوی خطوط guard/implementation. هیچ render یا full test در این نوبت اجرا نشد.

**پایان گزارش: لطفاً یکی از تصمیم‌های ۱، ۲ یا ۳ را انتخاب کنید.**
