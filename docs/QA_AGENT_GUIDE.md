<div dir="rtl" align="right">

# راهنمای QA Agent — Branch QA

> **AgentFramework** · QA Maturity Pattern  
> تولید Test Case و Use Case از Branch + Acceptance Criteria + Feature Brief

---

## خلاصه

QA Agent یک Branch توسعه (مثلاً `feature/VEN-123-login`) را با Branch پایه مقایسه می‌کند، تغییرات کد را تحلیل می‌کند و خروجی QA ساخت‌یافته تولید می‌کند:

| خروجی | توضیح |
|-------|-------|
| **Test Cases** | سناریوهای تست با مراحل و نتیجه مورد انتظار |
| **Use Cases** | جریان‌های کاربری (Actor / Goal / Main Flow) |
| **Critical Flows** | جریان‌های حیاتی تحت تأثیر و ریسک Regression |
| **AC Coverage** | پوشش هر Acceptance Criterion نسبت به کد |
| **Gaps** | موارد تست‌نشده یا ناهماهنگی Spec/Code |
| **Automation Suggestions** | پیشنهاد تست خودکار (pytest، jest، cypress) |

---

## پیش‌نیازها

### ۱. تنظیم `.env`

```env
CURSOR_REPO_PATH=D:\path\to\your\git\clone
CURSOR_BRIDGE_URL=http://127.0.0.1:9090
```

| متغیر | کاربرد |
|-------|--------|
| `CURSOR_REPO_PATH` | مسیر clone محلی Git (برای `git diff`) |
| `CURSOR_BRIDGE_URL` | آدرس Cursor Bridge (پورت 9090) |

### ۲. اجرای سرویس‌ها

```powershell
py run_server.py
py run_cursor_bridge.py
```

### ۳. دسترسی به داشبورد

- **URL:** [http://localhost:8000/dashboard/qa](http://localhost:8000/dashboard/qa)
- **منو:** QA Agent (کنار Review)

---

## Templateها — لطفاً تکمیل کنید

قبل از اجرای QA، این فایل‌ها را برای هر تسک پر کنید:

| فایل | مسیر | محتوا |
|------|------|-------|
| **Acceptance Criteria** | `docs/templates/qa/ACCEPTANCE_CRITERIA_TEMPLATE.md` | Given/When/Then، Critical Flows، Out of Scope |
| **Feature Brief / PRD** | `docs/templates/qa/FEATURE_BRIEF_TEMPLATE.md` | User Stories، FR/NFR، Definition of Done |

### Placeholderها

| Placeholder | مثال |
|-------------|------|
| `{BRANCH_NAME}` | `feature/VEN-123-login` |
| `{TARGET_BRANCH}` | `develop` |
| `{JIRA_KEY}` | `VEN-123` |
| `{DATE}` | تاریخ امروز |

> در داشبورد دکمه **«بارگذاری Template»** همین فایل‌ها را با Branch و Jira Key پر می‌کند.

---

## نحوه استفاده (Dashboard)

1. به **`/dashboard/qa`** بروید
2. **Feature Branch** را وارد یا انتخاب کنید (مثلاً `feature/VEN-123-my-task`)
3. **Target Branch** را در صورت نیاز تنظیم کنید (پیش‌فرض: `develop` از settings)
4. **«بارگذاری Template»** → Acceptance Criteria و Feature Brief را **تکمیل** کنید
5. زبان خروجی را انتخاب کنید (فارسی / English)
6. **«اجرای QA»** را بزنید
7. نتایج را در تب‌های Summary، Test Cases، Use Cases، AC Coverage و Critical Flows ببینید

---

## Verdictها

| Verdict | معنی |
|---------|------|
| **PASS** | پوشش AC کافی — آماده QA sign-off |
| **PASS_WITH_GAPS** | قابل release با gapهای جزئی |
| **NEEDS_INPUT** | Template ناقص — AC یا PRD را تکمیل کنید |
| **FAIL** | مشکل جدی در QA یا پوشش ناکافی |
| **PENDING** | در حال پردازش یا پاسخ نامشخص |

---

## API

| Method | Endpoint | توضیح |
|--------|----------|-------|
| `GET` | `/api/v1/qa/templates` | Templateهای AC و Feature Brief |
| `GET` | `/api/v1/qa/branches` | لیست Branchها |
| `POST` | `/api/v1/qa/analyze` | اجرای QA روی Branch |
| `GET` | `/api/v1/qa/runs` | تاریخچه اجراها |
| `GET` | `/api/v1/qa/runs/{run_id}` | جزئیات یک اجرا |

### نمونه درخواست Analyze

```json
POST /api/v1/qa/analyze
{
  "branch_name": "feature/VEN-123-login",
  "target_branch": "develop",
  "acceptance_criteria": "...",
  "feature_brief": "...",
  "title": "Login feature",
  "language": "fa"
}
```

---

## معماری (خلاصه)

```
Dashboard (/dashboard/qa)
    → POST /api/v1/qa/analyze
    → QaService (git diff + context)
    → execute_qa (Cursor Bridge / LLM)
    → QaResult (test_cases, use_cases, ac_coverage, …)
    → SQLite (agent_runs)
```

| مسیر | نقش |
|------|-----|
| `src/api/routes/qa.py` | API routes |
| `src/api/services/qa_service.py` | Orchestration |
| `src/shared/qa/` | Models، prompt، git diff، parser |
| `src/shared/agent_executors/qa_executor.py` | Cursor / LLM executor |
| `src/cursor_bridge/server.py` | Endpoint `/qa` |
| `src/dashboard/static/qa.html` | UI داشبورد |

---

## عیب‌یابی

| مشکل | راه‌حل |
|------|--------|
| `CURSOR_REPO_PATH is not set` | مسیر clone Git را در `.env` تنظیم کنید |
| `Cursor Bridge not reachable` | `py run_cursor_bridge.py` را اجرا کنید |
| `git diff failed` | Branch را به `origin` push کنید؛ target branch موجود باشد |
| Verdict = **NEEDS_INPUT** | Templateهای AC و Feature Brief را کامل کنید |
| `python` not found | از `py` به‌جای `python` استفاده کنید |

---

## تست

```powershell
py -m pytest tests/test_qa_agent.py -q
```

---

## Export — pytest / Cypress

پس از اجرای QA:

| روش | Endpoint / UI |
|-----|----------------|
| Dashboard | دکمه **Export pytest + Cypress** |
| API | `POST /api/v1/qa/runs/{run_id}/export` |

```json
{
  "formats": ["pytest", "cypress", "markdown"],
  "commit_to_branch": false
}
```

| فایل | مسیر |
|------|------|
| pytest | `tests/generated/test_{jira}_{slug}.py` |
| Cypress | `cypress/e2e/{jira}_{slug}.cy.ts` |
| Markdown | `docs/qa/{jira}_test_cases.md` |

فایل‌ها در `data/qa_exports/{run_id}/` ذخیره می‌شوند.

برای commit خودکار به Branch: `QA_EXPORT_COMMIT_TO_BRANCH=true` در `.env`

---

## Attach Test Case به Jira

| روش | Endpoint / UI |
|-----|----------------|
| Dashboard | دکمه **Attach to Jira** |
| API | `POST /api/v1/qa/runs/{run_id}/attach-jira` |

```json
{ "issue_key": "VEN-123" }
```

- Comment با verdict و summary به Jira اضافه می‌شود
- فایل Markdown Test Cases به‌صورت attachment آپلود می‌شود
- `issue_key` از Branch استخراج می‌شود اگر ارسال نشود

---

## Quality Gate — Release Pipeline

### تنظیم `.env`

```env
QA_GATE_ENABLED=true
QA_GATE_ALLOWED_VERDICTS=PASS,PASS_WITH_GAPS
```

### رفتار

- قبل از trigger Stage pipeline (`Deploy Request`)، QA آخرین Branch بررسی می‌شود
- اگر verdict مجاز نباشد → pipeline trigger **block** می‌شود
- متغیر `QA_VERDICT` به pipeline GitLab پاس داده می‌شود

### GitLab CI

```yaml
qa_gate:
  script:
    - curl -f "$AGENT_FRAMEWORK_URL/api/v1/qa/gate?branch=$CI_COMMIT_REF_NAME"
```

| Endpoint | پاس | Fail |
|----------|-----|------|
| `GET /api/v1/qa/gate?branch=feature/...` | 200 | 403 |

---

## DORA Metrics

Dashboard → بخش **DORA Metrics (30 days)** در `/dashboard/qa`

| API | `GET /api/v1/qa/metrics?days=30` |

| متریک | منبع |
|--------|------|
| **Deployment Frequency** | Deploy Requests / هفته |
| **Lead Time (QA)** | میانگین زمان تحلیل QA |
| **Change Failure Rate** | verdict=FAIL / کل QA runs |
| **Pass Rate** | PASS + PASS_WITH_GAPS |
| **MTTR** | نیاز به Aegis incident (فعلاً N/A) |

</div>