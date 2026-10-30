# RTK — کاهش مصرف توکن در Review

[RTK (Rust Token Killer)](https://github.com/rtk-ai/rtk) یک CLI proxy است که خروجی دستورات shell (به‌خصوص `git diff`) را **فشرده** می‌کند قبل از اینکه وارد context window مدل شود. در AgentFramework از RTK برای **کاهش حجم git diff داخل prompt مرور کد Sentinel** استفاده می‌شود.

---

## چرا RTK در Review؟

بزرگ‌ترین بخش prompt review معمولاً **git diff** است:

```
Review Context = diff + review rules + specs + skill checklist + …
```

MRهای بزرگ می‌توانند diff ده‌ها هزار token مصرف کنند. RTK با این استرategی‌ها حجم را کم می‌کند:

| استراتژی RTK | اثر در Review |
|--------------|----------------|
| **Smart Filtering** | حذف noise (خطوط خالی اضافی، boilerplate) |
| **Truncation** | کاهش خطوط context در hunks |
| **Grouping** | خلاصه‌سازی خروجی |
| **Deduplication** | ادغام تکرارها |

> **توجه:** RTK عمدتاً **bash output** را فشرده می‌کند؛ کاهش واقعی bill به prompt کلی، output tokens، و cache بستگی دارد. برای MR review، diff معمولاً بزرگ‌ترین slice قابل کنترل است.

---

## معماری در AgentFramework

```
GitLab MR diff (raw)
        │
        ▼
format_mr_diff()  ──► git_diff_raw  ──► diff_rule_scanner (RR-012/013/014)
        │
        ▼
RTK compress (rtk git diff | internal fallback)
        │
        ▼
git_diff (prompt) ──► build_review_prompt() ──► Cursor CLI
```

**مهم:** diff **خام** (`git_diff_raw`) برای scanner قطعی حفظ می‌شود؛ diff **فشرده** (`git_diff`) فقط در prompt LLM embed می‌شود.

---

## نصب RTK

### Windows (پیشنهادی)

1. از [Releases](https://github.com/rtk-ai/rtk/releases) فایل `rtk-x86_64-pc-windows-msvc.zip` را دانلود کنید.
2. `rtk.exe` را در PATH قرار دهید، مثلاً:
   ```
   C:\Users\<you>\.local\bin\rtk.exe
   ```
3. تأیید:
   ```powershell
   rtk --version
   rtk gain
   ```

### Homebrew / Linux / Cargo

```bash
brew install rtk
# یا
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
# یا
cargo install --git https://github.com/rtk-ai/rtk
```

### Cursor hook (اختیاری — برای develop، نه review pipeline)

```bash
rtk init -g --agent cursor
```

این hook فقط **Bash tool calls** در Cursor را rewrite می‌کند. pipeline Review AgentFramework مستقیماً `rtk` را از Python صدا می‌زند.

---

## تنظیمات `.env`

```env
# فعال/غیرفعال فشرده‌سازی diff در review (پیش‌فرض: false)
CURSOR_REVIEW_USE_RTK=false

# مسیر binaire (پیش‌فرض: rtk در PATH)
RTK_BIN=rtk

# timeout subprocess RTK (ثانیه)
RTK_TIMEOUT_SECONDS=60

# fallback داخلی: حداکثر خط context در هر hunk وقتی RTK نصب نیست
CURSOR_REVIEW_RTK_MAX_CONTEXT_LINES=3
```

| متغیر | پیش‌فرض | توضیح |
|--------|---------|--------|
| `CURSOR_REVIEW_USE_RTK` | `false` | `true` = فشرده‌سازی diff در prompt |
| `RTK_BIN` | `rtk` | مسیر کامل `rtk.exe` در Windows |
| `RTK_TIMEOUT_SECONDS` | `60` | timeout برای `rtk git diff` |
| `CURSOR_REVIEW_RTK_MAX_CONTEXT_LINES` | `3` | context lines در fallback داخلی |

---

## ترتیب فشرده‌سازی (خودکار)

کد در `src/shared/cursor_cli/rtk_compress.py`:

| اولویت | روش | شرط |
|--------|-----|-----|
| 1 | **`rtk_git`** | worktree/repo موجود + `rtk` نصب → `rtk git diff origin/{target}...HEAD` |
| 2 | **`rtk_diff`** | `rtk` نصب + diff text (best-effort) |
| 3 | **`internal`** | همیشه — trim context، حفظ همه خطوط `+`/`-` |
| 4 | **`none`** | `CURSOR_REVIEW_USE_RTK=false` |

---

## مشاهده در Dashboard

### صفحه RTK Savings

**URL:** `/dashboard/rtk` — منوی **RTK Savings**

دو تب:

| تب | محتوا |
|----|--------|
| **Review Savings** | هر بار فشرده‌سازی diff در MR Review — tokens قبل/بعد، method، MR |
| **RTK CLI Global** | خروجی `rtk gain --all --format json` (آمار global hook RTK روی shell) |

API:

- `GET /api/v1/rtk/savings` — لیست events + aggregate
- `GET /api/v1/rtk/stats` — فقط aggregate
- `GET /api/v1/rtk/gain` — proxy به RTK CLI
- `GET /api/v1/rtk/health` — نصب بودن binary

### Review Steps (live)

بعد از Review، در **Review Steps** event **`rtk`** را می‌بینید:

```
[rtk] Diff compressed for review prompt — internal: 4,200 → 1,850 tokens (56% smaller)
```

یا با RTK نصب:

```
[rtk] Diff compressed for review prompt — rtk_git: 4,200 → 980 tokens (77% smaller)
```

در **Review Context meta** و `extra_context.rtk_compression` هم یادداشت فشرده‌سازی ذخیره می‌شود.

---

## فایل‌های مرتبط

| فایل | نقش |
|------|-----|
| `src/shared/cursor_cli/rtk_compress.py` | RTK wrapper + fallback داخلی |
| `src/shared/cursor_cli/context_builder.py` | اعمال RTK هنگام ساخت ReviewContext |
| `src/shared/agent_executors/review_executor.py` | RTK با worktree + SSE step |
| `src/shared/cursor_cli/models.py` | `git_diff` + `git_diff_raw` |
| `src/shared/cursor_cli/diff_rule_scanner.py` | از `git_diff_raw` استفاده می‌کند |
| `tests/test_rtk_compress.py` | تست fallback |

---

## عیب‌یابی

| علامت | راه‌حل |
|--------|--------|
| `method=internal` همیشه | `rtk` در PATH نیست — نصب کنید یا `RTK_BIN` را set کنید |
| scanner findings از دست رفت | نباید — scanner روی `git_diff_raw` است؛ issue بزنید |
| `rtk git diff` خالی | target branch روی origin fetch نشده؛ `git fetch origin {target}` |
| فشرده‌سازی کم | MR کوچک است یا diff از قبل کوتاه |
| Name collision با Rust Type Kit | از [rtk-ai/rtk](https://github.com/rtk-ai/rtk) استفاده کنید، نه crates.io |

---

## محدودیت‌ها

1. **RTK ≠ 90% bill reduction** — فقط slice مربوط به diff در prompt.
2. **Review rules / specs** هنوز full-text در prompt هستند (`CURSOR_REVIEW_INCLUDE_SPECS`).
3. **`rtk diff` روی patch file** best-effort است؛ **`rtk git diff` در worktree** reliable‌تر است.
4. برای MR بدون worktree، fallback **internal** استفاده می‌شود.

---

## مرجع

- RTK GitHub: https://github.com/rtk-ai/rtk
- Sentinel Review Flow: [SENTINEL_REVIEW_FLOW.md](./SENTINEL_REVIEW_FLOW.md)
- Knowledge + SDLC: [KNOWLEDGE_AGENT_AND_AI_SDLC.md](../KNOWLEDGE_AGENT_AND_AI_SDLC.md)
