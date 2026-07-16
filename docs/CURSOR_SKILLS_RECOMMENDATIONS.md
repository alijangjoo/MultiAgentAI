# پیشنهاد Skill و Rule برای ادامهٔ توسعه AgentFramework

این سند خروجی اسکن (بدون تغییر کد) است: کدام Skill/Ruleهای Cursor دقت را بالا می‌برند و مصرف توکن را کم می‌کنند.

**وضعیت فعلی پروژه**

- پلتفرم orchestration چندعامله: LangGraph + FastAPI + HITL + RAG (Sage/Chroma) + Cursor Bridge
- عامل‌ها: Atlas → Forge → Sentinel → HITL → Scribe، به‌علاوه Aegis، Meridian، Deploy، Sage
- دانش دامنه قبلاً در `data/specs/` و promptهای inline Forge/Sentinel هست
- هنوز **هیچ** `.cursor/rules` یا project skill داخل این ریپو وجود ندارد

---

## ۱. تفاوت Rule و Skill (برای صرفه‌جویی توکن)

| ابزار | کی وارد context می‌شود | مناسب برای |
|--------|-------------------------|------------|
| **Rule** (`.cursor/rules/*.mdc`) | همیشه یا وقتی فایل‌های matching بازند | قراردادهای کوتاه و ثابت |
| **Skill** (`.cursor/skills/*/SKILL.md`) | فقط وقتی مرتبط است یا صریحاً صدا زده شود | workflowهای تکراری و جزئیات دامنه |

**قانون طلایی:** ruleها را کوتاه و چندتکه نگه دارید؛ جزئیات معماری را داخل skill با progressive disclosure بگذارید، نه داخل `alwaysApply: true`.

---

## ۲. Skillهای آماده‌ای که همین الان باید استفاده شوند

این‌ها built-in Cursor هستند؛ لازم نیست ساخته شوند. موقع کار مرتبط صدا زده شوند یا auto-invoke شوند.

### ۲.۱ `sdk` — بالاترین اولویت

چون `src/cursor_bridge/` با `cursor-sdk` و `Agent.create` / `send` کار می‌کند.

**کی استفاده شود**

- کار روی bridge، executor، model، local vs cloud، streaming
- خطای SDK یا تغییر قرارداد `/develop` و `/review`

**فایده**

- جلوی حدس‌زدن API و ریشه‌ای اشتباه را می‌گیرد
- رفت‌وبرگشت و مصرف توکن کمتر می‌شود

### ۲.۲ `create-rule` و `create-skill`

برای ساخت زیرساخت دقت پروژه (بخش‌های ۳ و ۴ همین سند).

### ۲.۳ به‌صورت موردی

| Skill | کی استفاده شود |
|-------|----------------|
| `create-hook` | اگر بعد از commit/edit بخواهید چک‌لیست HITL یا تست slice خودکار اجرا شود |
| `babysit` | وقتی PR باز است و می‌خواهید CI/commentها را بدون توضیح تکراری جلو ببرید |
| `review-security` / `review-bugbot` | قبل از ادغام تغییرات روی bridge، webhook، یا deploy HITL |
| `split-to-prs` | وقتی یک چت بزرگ (مثلاً PM + deploy + knowledge) را به چند PR کوچک بشکنید |
| `update-cursor-settings` | فقط اگر بخواهید رفتار ادیتور Cursor را برای تیم یکدست کنید |

**اولویت پایین برای این پروژه:** `canvas`، `statusline`، `automate`، `loop`

---

## ۳. Rules پیشنهادی داخل AgentFramework

مسیر: `.cursor/rules/*.mdc`  
محتوا باید کوتاه، actionable و scoped باشد.

### ۳.۱ `architecture-slices.mdc`

- **globs:** `src/slices/**/*.py`
- **قانون:** هر قابلیت فقط داخل vertical slice خودش؛ agent جدید = graph + orchestrator + route؛ الگوی مرجع = Feature Pipeline

### ۳.۲ `integrations-protocol.mdc`

- **globs:** `src/shared/integrations/**/*.py`
- **قانون:** از `factory` / `registry` / protocol استفاده شود؛ مستقیم client نوشته نشود؛ mock و real یکسان بمانند

### ۳.۳ `cursor-bridge.mdc`

- **globs:** `src/cursor_bridge/**/*.py`, `src/shared/agent_executors/**/*.py`
- **قانون:** قرارداد `/develop` و `/review`، envها، مدل پیش‌فرض، و اینکه SDK فقط از bridge صدا زده شود

### ۳.۴ `no-readme-drift.mdc` (اختیاری)

- خیلی کوتاه
- وقتی slice اضافه شد، ساختار README به‌روز شود

### ۳.۵ Always Apply (حداکثر یک قانون خیلی کوتاه)

فقط برای حدود ۲۰ خط قوانین جهانی، مثلاً:

- Python 3.11+
- pydantic-settings برای کانفیگ
- بدون commit خودسرانه

از `alwaysApply: true` برای داکومنت طولانی معماری استفاده نکنید.

---

## ۴. Project Skills پیشنهادی داخل AgentFramework

مسیر: `.cursor/skills/<name>/SKILL.md`

| Skill پیشنهادی | کاربرد | چرا توکن کم می‌کند |
|-----------------|--------|---------------------|
| `add-agent-slice` | ساخت agent/slice جدید با چک‌لیست ثابت | دیگر هر بار explainer کامل معماری بازگو نمی‌شود |
| `forge-develop-contract` | قرارداد prompt/output Forge و پل Cursor | با promptهای پراکنده در `develop_executor` هم‌تراز می‌شود |
| `sentinel-review-format` | فرمت findings/suggestions Sentinel | خروجی review یکدست می‌شود |
| `hitl-checkpoint` | اضافه/تغییر دروازه HITL + persistence + dashboard | الگوی تکراری را کوتاه می‌کند |
| `knowledge-spec-ingest` | نوشتن/اسکن/ingest spec مطابق `SPEC_TEMPLATE` | از بازنویسی قواعد Sage جلوگیری می‌کند |
| `deploy-request-flow` | poller، webhook، LangGraph، Mattermost | جزئیات deploy فقط وقتی لازم لود می‌شود |

**نکته ساخت Skill**

- در `SKILL.md` فقط قوانین اجرایی بگذارید
- جزئیات را در `reference.md` / `examples.md` لینک کنید (progressive disclosure)
- description را سوم‌شخص و با trigger terms بنویسید
- از skillهای مبهم مثل `helper` یا `utils` پرهیز کنید

---

## ۵. Skills پیشنهادی روی ریپوی Dizi

`CURSOR_REPO_PATH` جدا از این فریمورک است و Cursor واقعاً آنجا کد می‌زند. این skills برای Forge/Sentinel حیاتی‌اند.

1. **`dizi-new-structure-ddd`** — خلاصهٔ `dizi.new-structure.*` + قوانین DDD/CQRS
2. **`dizi-legacy-feature-module`** — خلاصهٔ الگوهای legacy
3. **`dizi-branch-naming`** — الگوی `Feature/[task-key]-[slug]` از `branch_naming.py`
4. **per-BC skills** فقط برای BCهای پرتکرار (مثلاً vendors / orders) — نه همهٔ فایل‌های `data/specs/` به‌صورت always-load

**مهم:** محتوای خام همهٔ `data/specs/*.md` را داخل یک skill غول‌آسا نریزید. در `SKILL.md` فقط قوانین اجرایی بگذارید و به فایل spec / `reference.md` لینک دهید.

منبع محتوای موجود:

- `data/specs/*.md`
- `docs/specs/SPEC_TEMPLATE.md`
- `docs/templates/PRD_TEMPLATE.md`
- promptهای `src/shared/agent_executors/develop_executor.py` و `review_executor.py`

---

## ۶. ترتیب پیشنهادی اجرا

```text
هفته ۱ (کمترین توکن، بیشترین دقت)
1) create-rule → 3 rule کوتاه برای slices / integrations / bridge
2) create-skill → add-agent-slice
3) همیشه موقع کار روی bridge: skill sdk

هفته ۲ (هم‌تراز کردن agentهای کدنویس)
4) Skills روی Dizi: new-structure + branch-naming
5) Skills فریمورک: forge-develop-contract + sentinel-review-format

هفته ۳ (عملیات)
6) hitl-checkpoint + deploy-request-flow + knowledge-spec-ingest
7) در صورت نیاز: create-hook برای تست smoke بعد از تغییر executor
```

---

## ۷. کارهایی که عمداً نباید انجام شوند (توکن‌سوز)

- کپی کردن همهٔ `data/specs/` داخل یک rule با `alwaysApply: true`
- یک skill به نام `helper` / `utils` که همه‌چیز را قاطی کند
- نگه‌داشتن همان متن هم در prompt Forge و هم در skill بدون اینکه یکی منبع حقیقت باشد
- گذاشتن توضیح طولانی عمومی («LangGraph چیست») داخل skill — مدل بلد است؛ فقط **قرارداد پروژه** را بنویسید
- skill/rule خیلی بلند (بدنهٔ اصلی بهتر است زیر حدود ۵۰ خط برای rule و زیر ۵۰۰ خط برای `SKILL.md` بماند)

---

## ۸. جمع‌بندی

شما الان orchestrator قوی دارید، ولی Cursor هنوز «حافظهٔ پروژه» ساخت‌یافته ندارد.

برای ادامه:

- **Rules کوتاه** برای قرارداد کد
- **Skills جدا** برای هر workflow تکراری
- **استفاده اجباری از skill `sdk`** روی bridge

بیشترین دقت و کمترین توکن را می‌دهد.

---

## ۹. منابع معماری مرتبط در ریپو

| مسیر | نقش |
|------|-----|
| `src/slices/feature_pipeline/` | Atlas / Forge / Sentinel / Scribe + develop workflow |
| `src/slices/incident_response/` | Aegis |
| `src/slices/product_manager/` | Meridian |
| `src/slices/deploy_request/` | Deploy + HITL + Mattermost |
| `src/slices/knowledge/` | Sage RAG + specs scanner/store |
| `src/cursor_bridge/server.py` | پل محلی Cursor SDK |
| `src/shared/agent_executors/` | انتخاب executor و قرارداد develop/review |
| `data/specs/` | معماری Dizi برای Forge/Sentinel/RAG |
| `docs/specs/SPEC_TEMPLATE.md` | قالب spec / Rules for Agents |

---

*تولید شده از اسکن توصیه‌ای Cursor Skills؛ کد پروژه در آن مرحله تغییر نکرده است.*
