# راه‌اندازی Langfuse برای AgentFramework

این راهنما نحوهٔ فعال‌سازی **Langfuse** را برای trace کردن اجرای agentها، مشاهدهٔ هر run به‌صورت جداگانه، و مانیتoring هزینه و latency توضیح می‌دهد.

## Langfuse چه کاری انجام می‌دهد؟

| قابلیت | توضیح |
|--------|--------|
| **Traces** | هر فراخوانی LLM (Atlas، Forge، Sentinel، Sage، …) با prompt، response، token و زمان |
| **Sessions** | همهٔ traceهای یک agent run با `run_id` گروه‌بندی می‌شوند |
| **Dashboards** | هزینه، حجم، و latency به‌صورت aggregate در UI Langfuse |

---

## پیش‌نیازها

1. Python 3.11+
2. نصب وابستگی‌های پروژه
3. حساب در [cloud.langfuse.com](https://cloud.langfuse.com) (یا self-host)

### نصب یکجا

```powershell
cd D:\Python\Multi-Agents\AgentFramework
py -m pip install -r requirements-dev.txt
```

---

## ۱. ساخت پروژه در Langfuse

1. وارد [cloud.langfuse.com](https://cloud.langfuse.com) شوید.
2. یک **Project** بسازید (مثلاً `AgentFramework`).
3. بروید به **Settings → API Keys**.
4. دو کلید جدا کپی کنید:

| نام در Langfuse | پیشوند | متغیر در `.env` |
|-----------------|--------|-----------------|
| **Public Key** | `pk-lf-...` | `LANGFUSE_PUBLIC_KEY` |
| **Secret Key** | `sk-lf-...` | `LANGFUSE_SECRET_KEY` |

> **مهم:** Public Key با `pk-lf-` شروع می‌شود؛ Secret Key با `sk-lf-`. هر دو نباید یکسان باشند.

---

## ۲. تنظیم `.env`

در root پروژه (`D:\Python\Multi-Agents\AgentFramework\.env`):

```env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
LANGFUSE_HOST=https://cloud.langfuse.com
```

برای self-host محلی:

```env
LANGFUSE_HOST=http://localhost:3000
```

نمونهٔ کامل در `.env.example` موجود است.

---

## ۳. اجرای سرویس‌ها

```powershell
cd D:\Python\Multi-Agents\AgentFramework
py run_server.py
```

در ترمینال جدا (برای develop/review با Cursor Bridge):

```powershell
py run_cursor_bridge.py
```

---

## ۴. بررسی سلامت

```powershell
curl http://127.0.0.1:8080/health
```

خروجی مطلوب:

```json
"tracing": {
  "enabled": true,
  "configured": true,
  "host": "https://cloud.langfuse.com",
  "dashboard_url": "https://cloud.langfuse.com/",
  "reason": null
}
```

### معنی فیلد `reason`

| مقدار | علت | راه‌حل |
|-------|-----|--------|
| `disabled` | `LANGFUSE_ENABLED=false` | `true` کنید |
| `placeholder_keys` | کلید هنوز `pk-lf-...` یا `PASTE_...` است | کلید واقعی از Langfuse |
| `invalid_public_key` | Public Key با `pk-lf-` شروع نشده | Public Key درست را بگذارید |
| `invalid_secret_key` | Secret Key با `sk-lf-` شروع نشده | Secret Key درست را بگذارید |
| `duplicate_keys` | Public و Secret یکسانند | هر دو را جدا کپی کنید |
| `null` | همه‌چیز OK | — |

---

## ۵. مشاهده traceهای هر اجرا

1. یک workflow از dashboard اجرا کنید (مثلاً develop، review، knowledge).
2. `run_id` را از dashboard یا API بردارید (`GET /api/v1/runs`).
3. در Langfuse → **Tracing → Traces**:
   - فیلتر **Session ID** = همان `run_id`
4. هر span شامل:
   - نام agent (`atlas`, `forge`, `sentinel`, `sage`, …)
   - ورودی/خروجی LLM
   - token usage و latency

### Cursor Bridge

فراخوانی‌های `/develop` و `/review` روی پورت 9090 به‌صورت `cursor_develop` / `cursor_review` ثبت می‌شوند و با همان `run_id` در session دیده می‌شوند.

---

## ۶. Dashboards (هزینه و performance)

در Langfuse → **Dashboards**:

- **Cost** — هزینه بر اساس model و agent
- **Latency** — p50 / p95 زمان generation
- **Volume** — تعداد trace در بازهٔ زمانی

فیلتر با metadata:
- `agent_name`
- `workflow_type` (مثلاً `feature_development`, `code_review`, `knowledge_query`)

---

## معماری در این پروژه

```
FastAPI (run_server.py)
  └─ init_tracing() در lifespan
  └─ LangGraph agents → trace_config(run_id, agent_name, ...)
       └─ Langfuse CallbackHandler (LangChain)

Cursor Bridge (run_cursor_bridge.py)
  └─ record_generation() برای 9Router / Cursor SDK
```

فایل‌های مرتبط:

| فایل | نقش |
|------|-----|
| `src/core/tracing.py` | init، callback، ثبت generation |
| `src/core/config.py` | خواندن متغیرهای `LANGFUSE_*` |
| `src/main.py` | startup / shutdown tracing |
| `src/cursor_bridge/server.py` | trace برای develop/review |

---

## عیب‌یابی

### `ModuleNotFoundError: No module named 'langfuse'`

```powershell
py -m pip install -r requirements-dev.txt
```

### `Please install langchain to use the Langfuse langchain integration`

پکیج `langchain` (meta-package) لازم است، نه فقط `langchain-core`:

```powershell
py -m pip install langchain
```

### تغییرات `.env` اعمال نمی‌شود

1. فایل را **Save** کنید (`Ctrl+S`).
2. سرور را **ری‌استارت** کنید.
3. مطمئن شوید همان Python نصب و اجرا می‌شود:

```powershell
py -m pip install -r requirements-dev.txt
py run_server.py
```

### trace در Langfuse نمی‌آید

- `LANGFUSE_ENABLED=true` و کلیدهای معتبر
- `/health` → `"enabled": true`
- بعد از workflow چند ثانیه صبر کنید (flush در shutdown یا به‌صورت async)
- Session ID = `run_id` agent run

---

## امنیت

- Secret Key را commit نکنید (`.env` در git نباشد).
- در صورت لو رفتن کلید، در Langfuse کلید جدید بسازید و قبلی را revoke کنید.

---

## غیرفعال کردن

```env
LANGFUSE_ENABLED=false
```

بدون Langfuse، agentها مثل قبل کار می‌کنند؛ فقط trace ارسال نمی‌شود.
