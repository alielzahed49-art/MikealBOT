"""
================================================================================
  لوحة ميكائيل — ملف واحد
================================================================================
  التشغيل محلياً:      python app.py
  التشغيل على Render:  gunicorn app:app --workers 1 --threads 8 --timeout 120

  خريطة الملف (دوّر على العناوين دي عشان توصل بسرعة):
     [١] الإعدادات
     [٢] قاعدة البيانات
     [٣] التعامل مع اللعبة
     [٤] محرّك المهام
     [٥] التصميم وكود الواجهة
     [٦] صفحات HTML
     [٧] المسارات
     [٨] الإقلاع
================================================================================
"""
import hmac
import json
import logging
import os
import random
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps

import psycopg2
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import (
    Flask, Response, jsonify, redirect, render_template_string,
    request, session, url_for,
)
from psycopg2 import pool as pgpool
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mikael")


# ==============================================================================
#  [١] الإعدادات
# ==============================================================================

def _int(key, default):
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


# رابط الـ Session Pooler من Supabase (مش الرابط المباشر — Render المجاني IPv4)
DATABASE_URL = os.environ.get("DATABASE_URL", "")

OWNER_USER = os.environ.get("OWNER_USER", "mikael")
OWNER_PASS = os.environ.get("OWNER_PASS", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
CRON_SECRET = os.environ.get("CRON_SECRET", "")

BASE_URL = os.environ.get("GAME_BASE_URL", "https://diplomacia.com.tr/api")
GAME_ORIGIN = os.environ.get("GAME_ORIGIN", "https://diplomacia.com.tr")
REQUEST_TIMEOUT = _int("REQUEST_TIMEOUT", 20)

TICK_SECONDS = _int("TICK_SECONDS", 120)
PROFILE_REFRESH_MIN = _int("PROFILE_REFRESH_MIN", 30)
MAX_TASKS_PER_TICK = _int("MAX_TASKS_PER_TICK", 25)
LOG_KEEP = _int("LOG_KEEP", 400)

# التباعد العشوائي بين الحسابات في الأوامر الجماعية (بالثواني)
GROUP_SPREAD_MIN = _int("GROUP_SPREAD_MIN", 15)
GROUP_SPREAD_MAX = _int("GROUP_SPREAD_MAX", 90)

# خطة التطوير بالتتابع: مسافة بين كل ترقية والتانية جوه نفس الحساب،
# وأقصى عدد ترقيات مسموح بيه في الخطوة الواحدة وفي الخطة كلها (حماية من الأغلاط)
# خطة التطوير بالتتابع: أقصى عدد ترقيات مسموح بيه في الخطوة الواحدة وفي الخطة
# كلها (حماية من الأغلاط). مفيش "مدة ثابتة بين الخطوات" — الوقت الحقيقي بييجي
# من اللعبة نفسها بعد كل محاولة (شوف skill_cooldown_seconds).
MAX_PLAN_STEP_COUNT = _int("MAX_PLAN_STEP_COUNT", 300)
MAX_PLAN_TOTAL_COUNT = _int("MAX_PLAN_TOTAL_COUNT", 1000)

# أقصى وقت نسيب فيه شارة "بيسافر" ظاهرة من غير تأكيد وصول
TRAVEL_TIMEOUT_MINUTES = _int("TRAVEL_TIMEOUT_MINUTES", 60)

APP_NAME = os.environ.get("APP_NAME", "لوحة ميكائيل")

PERKS = {
    "barracks":       {"key": "kisla",            "label": "الثكنات"},
    "war_techniques": {"key": "savas_teknikleri", "label": "تقنيات الحرب"},
    "scientist":      {"key": "bilim_insani",     "label": "العالِم"},
    "supply_drill":   {"key": "ikmal_talim",      "label": "الإمداد والتدريب"},
}
PERK_KEYS = {k: v["key"] for k, v in PERKS.items()}

CURRENCIES = {"money": "المال", "diamond": "الماس"}


def now():
    return datetime.now(timezone.utc)


# ==============================================================================
#  [٢] قاعدة البيانات
# ==============================================================================

_pool = None
_pool_lock = threading.Lock()
_schema_ready = False


def _build_pool():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL فاضي — حط رابط الـ Session Pooler بتاع Supabase")
    return pgpool.ThreadedConnectionPool(
        minconn=1, maxconn=5, dsn=DATABASE_URL,
        cursor_factory=RealDictCursor, connect_timeout=10,
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
    )


def get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = _build_pool()
    return _pool


@contextmanager
def connection():
    """بياخد اتصال ويرجّعه مهما حصل. لو الاتصال بايظ بنبني pool جديد."""
    global _pool
    p = get_pool()
    conn = None
    try:
        conn = p.getconn()
        yield conn
        conn.commit()
    except psycopg2.OperationalError:
        if conn is not None:
            try:
                p.putconn(conn, close=True)
            except Exception:
                pass
            conn = None
        with _pool_lock:
            try:
                p.closeall()
            except Exception:
                pass
            _pool = None
        raise
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn is not None:
            try:
                p.putconn(conn)
            except Exception:
                pass


def db_all(sql, params=None):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return [dict(r) for r in cur.fetchall()]


def db_one(sql, params=None):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
            return dict(row) if row else None


def db_execute(sql, params=None, returning=False):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if returning:
                row = cur.fetchone()
                return dict(row) if row else None
            return cur.rowcount


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            SERIAL PRIMARY KEY,
    label         TEXT NOT NULL DEFAULT '',
    token         TEXT NOT NULL DEFAULT '',
    enabled       BOOLEAN NOT NULL DEFAULT FALSE,
    squad         TEXT NOT NULL DEFAULT 'المجموعة الأولى',
    sort_order    INTEGER NOT NULL DEFAULT 0,

    perk          TEXT NOT NULL DEFAULT 'scientist',
    currency      TEXT NOT NULL DEFAULT 'money',
    auto_upgrade  BOOLEAN NOT NULL DEFAULT FALSE,
    auto_quests   BOOLEAN NOT NULL DEFAULT FALSE,
    auto_wheel    BOOLEAN NOT NULL DEFAULT FALSE,
    auto_work     BOOLEAN NOT NULL DEFAULT FALSE,
    auto_pills    BOOLEAN NOT NULL DEFAULT FALSE,
    pills_limit   BIGINT NOT NULL DEFAULT 2500,
    auto_military BOOLEAN NOT NULL DEFAULT FALSE,
    military_joined_until TIMESTAMPTZ,
    upgrade_plan  JSONB,

    proxy_type    TEXT NOT NULL DEFAULT 'http',
    proxy_host    TEXT NOT NULL DEFAULT '',
    proxy_port    TEXT NOT NULL DEFAULT '',
    proxy_user    TEXT NOT NULL DEFAULT '',
    proxy_pass    TEXT NOT NULL DEFAULT '',
    proxy_note    TEXT NOT NULL DEFAULT '',

    game_name     TEXT NOT NULL DEFAULT '',
    avatar_url    TEXT NOT NULL DEFAULT '',
    level_num     TEXT NOT NULL DEFAULT '—',
    xp_pct        INTEGER NOT NULL DEFAULT 0,
    balance       TEXT NOT NULL DEFAULT '—',
    diamonds      TEXT NOT NULL DEFAULT '—',
    location      TEXT NOT NULL DEFAULT '',
    nation        TEXT NOT NULL DEFAULT '',
    travel_destination TEXT NOT NULL DEFAULT '',
    travel_sent_at      TIMESTAMPTZ,
    lv_barracks   TEXT NOT NULL DEFAULT '?',
    lv_war        TEXT NOT NULL DEFAULT '?',
    lv_scientist  TEXT NOT NULL DEFAULT '?',
    lv_supply     TEXT NOT NULL DEFAULT '?',

    status        TEXT NOT NULL DEFAULT 'idle',
    last_error    TEXT NOT NULL DEFAULT '',
    last_seen     TIMESTAMPTZ,
    upgrade_until TIMESTAMPTZ,
    work_until    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tasks (
    id          SERIAL PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    result      TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(status, run_at);

CREATE TABLE IF NOT EXISTS logs (
    id         SERIAL PRIMARY KEY,
    account_id INTEGER,
    level      TEXT NOT NULL DEFAULT 'info',
    message    TEXT NOT NULL DEFAULT '',
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts DESC);
"""

# لو القاعدة كانت شغّالة من قبل بعمود أقل، الأسطر دي بتضيف الجديد من غير ما تلمس بياناتك
MIGRATIONS = [
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS travel_destination TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS travel_sent_at TIMESTAMPTZ",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS auto_pills BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS pills_limit BIGINT NOT NULL DEFAULT 2500",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS avatar_url TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS auto_military BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS military_joined_until TIMESTAMPTZ",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS upgrade_plan JSONB",
]


def init_db(force=False):
    """آمن نناديها كتير — بتشتغل فعلياً مرة واحدة بس بعد أول نجاح."""
    global _schema_ready
    if _schema_ready and not force:
        return
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            for stmt in MIGRATIONS:
                cur.execute(stmt)
    _schema_ready = True
    log.info("قاعدة البيانات جاهزة")


def add_log(message, level="info", account_id=None):
    try:
        db_execute(
            "INSERT INTO logs (account_id, level, message) VALUES (%s,%s,%s)",
            (account_id, level, str(message)[:500]),
        )
    except Exception as e:
        log.error("فشل تسجيل اللوج: %s", e)


def trim_logs():
    try:
        db_execute(
            "DELETE FROM logs WHERE id NOT IN "
            "(SELECT id FROM logs ORDER BY id DESC LIMIT %s)", (LOG_KEEP,)
        )
    except Exception as e:
        log.error("فشل تنظيف اللوج: %s", e)


# ==============================================================================
#  [٣] التعامل مع اللعبة
# ==============================================================================

_UA_POOL = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


class GameError(Exception):
    """خطأ راجع من اللعبة — الرسالة بتتعرض للمستخدم."""


class TokenInvalid(GameError):
    """التوكن مرفوض (401/403)."""


class AlreadyUpgrading(GameError):
    """
    فيه ترقية شغّالة بالفعل — اللعبة بتسمح بترقية واحدة بس في نفس الوقت
    للحساب كله (مش لكل مهارة لوحدها). remaining_seconds من رد اللعبة نفسها،
    مش رقم مخترع.
    """
    def __init__(self, message, remaining_seconds):
        super().__init__(message)
        self.remaining_seconds = remaining_seconds


class RateLimited(GameError):
    """اللعبة قالت "بطّئ" — نستنى المدة اللي هي حددتها بالظبط."""
    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = retry_after


def build_proxies(account):
    """بيحوّل بيانات البروكسي لصيغة requests. بيرجع None لو مفيش بروكسي."""
    host = (account.get("proxy_host") or "").strip()
    port = str(account.get("proxy_port") or "").strip()
    if not host or not port:
        return None
    scheme = (account.get("proxy_type") or "http").strip() or "http"
    user = (account.get("proxy_user") or "").strip()
    pwd = (account.get("proxy_pass") or "").strip()
    auth = f"{user}:{pwd}@" if user else ""
    url = f"{scheme}://{auth}{host}:{port}"
    return {"http": url, "https": url}


def parse_proxy_line(text):
    """
    بيفهم البروكسي من سطر واحد بالشكل: عنوان:منفذ:يوزر:باسورد
    (يوزر وباسورد اختياريين). بيرجع dict فيه host/port/user/pass أو None لو الصيغة غلط.
    """
    text = (text or "").strip()
    if not text:
        return {}
    parts = text.split(":")
    if len(parts) < 2:
        raise ValueError("الصيغة لازم تكون عنوان:منفذ أو عنوان:منفذ:يوزر:باسورد")
    host, port = parts[0].strip(), parts[1].strip()
    if not host or not port.isdigit():
        raise ValueError("العنوان أو المنفذ غلط — المنفذ لازم يكون رقم")
    user = parts[2].strip() if len(parts) > 2 else ""
    pwd = ":".join(parts[3:]).strip() if len(parts) > 3 else ""
    return {"proxy_host": host, "proxy_port": port, "proxy_user": user, "proxy_pass": pwd}


def _message_of(body):
    if not isinstance(body, dict):
        return ""
    for key in ("message", "error", "msg", "detail"):
        val = body.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


# كلمات اللعبة بترجّعها في رسالة الخطأ (تركي/إنجليزي — بنفحص الاتنين احتياطاً)
_ALREADY_UPGRADING_HINTS = [
    "başka bir beceri", "already upgrading", "devam ediyor",
    "upgrade in progress", "skill_upgrade_in_progress",
]
_RATE_LIMIT_HINTS = ["çok hızlı", "too many", "rate limit", "bekleyin", "wait", "dakika"]

_ALL_SKILL_KEYS = ["kisla", "savas_teknikleri", "bilim_insani", "ikmal_talim"]


def skill_cooldown_seconds(profile):
    """
    بيدوّر في بروفايل الحساب على أي مهارة (من الأربعة) عندها ترقية شغّالة دلوقتي،
    ويرجع الثواني المتبقية ليها. بيرجع None لو مفيش ترقية شغّالة خالص.
    اللعبة بتسمح بترقية واحدة بس في نفس الوقت للحساب كله، فمفيش فرق نتأكد من
    أنهي مهارة بالظبط — المهم نعرف إمتى الحساب هيبقى حر تاني.
    """
    if not isinstance(profile, dict):
        return None
    skills = profile.get("skills", {}) or {}
    for key in _ALL_SKILL_KEYS:
        pending_at = skills.get(f"{key}_pending_at")
        if pending_at:
            parsed = _parse_time(pending_at)
            if parsed:
                remaining = (parsed - datetime.now(timezone.utc)).total_seconds()
                return max(0, int(remaining))
    return None


class GameClient:
    def __init__(self, token, proxies=None, user_agent=None):
        self.token = (token or "").strip()
        self.proxies = proxies
        self.user_agent = user_agent or random.choice(_UA_POOL)
        self.session = requests.Session()

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": self.user_agent,
            "Origin": GAME_ORIGIN,
            "Referer": f"{GAME_ORIGIN}/",
        }

    def _request(self, method, path, json_body=None, params=None):
        try:
            r = self.session.request(
                method, f"{BASE_URL}{path}", headers=self._headers(),
                json=json_body, params=params, proxies=self.proxies,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            raise GameError(f"تعذّر الوصول للعبة: {type(e).__name__}") from e

        if r.status_code in (401, 403):
            raise TokenInvalid("التوكن مرفوض أو منتهي — لازم تجدده")

        body = {}
        if r.content:
            try:
                body = r.json()
            except ValueError:
                body = {"raw": r.text[:200]}
        return r.status_code, body

    def get(self, path, params=None):
        status, body = self._request("GET", path, params=params)
        if status in (200, 304):
            return body
        raise GameError(_message_of(body) or f"رد غير متوقع من اللعبة ({status})")

    def post(self, path, json_body=None):
        return self._request("POST", path, json_body=json_body or {})

    # ── نداءات اللعبة ────────────────────────────────────
    def profile(self):
        data = self.get("/players/profile")
        return data.get("player", data) if isinstance(data, dict) else {}

    def provinces(self):
        data = self.get("/provinces/all")
        return data.get("provinces", []) if isinstance(data, dict) else []

    def countries(self):
        data = self.get("/countries/leaderboard/countries")
        return data.get("countries", []) if isinstance(data, dict) else []

    def apply_visa(self, country_id):
        """POST /visas/apply {country_id} — طلب فيزا لدولة."""
        status, body = self.post("/visas/apply", {"country_id": country_id})
        if status in (200, 201) and body.get("success", True):
            return body
        raise GameError(_message_of(body) or f"طلب الفيزا اترفض ({status})")

    def apply_residence(self, country_id):
        """
        POST /residencies/apply {country_id} — طلب إقامة.
        ملحوظة: المسار ده متبني على قياس طلب الفيزا (نفس الشكل بالظبط) لأننا
        ملقيناش الطلب الحقيقي في الشبكة. لو رجّع 404 كده يبقى المسار غلط —
        راجع ملاحظة "طلب الإقامة" في الشرح تحت.
        """
        status, body = self.post("/residencies/apply", {"country_id": country_id})
        if status in (200, 201) and body.get("success", True):
            return body
        if status == 404:
            raise GameError(
                "مسار طلب الإقامة في اللعبة مختلف عن اللي متوقّع — "
                "لازم تتأكد منه من الشبكة (Network) وتبعتهولي أظبطه"
            )
        raise GameError(_message_of(body) or f"طلب الإقامة اترفض ({status})")

    def craft_pills(self, diamonds):
        """POST /auto/craft-pills {diamonds} — بيحوّل ماس لحبوب صحة (١ ماسة = ٥ حبات)."""
        status, body = self.post("/auto/craft-pills", {"diamonds": int(diamonds)})
        if status in (200, 201) and body.get("success", True):
            return body
        raise GameError(_message_of(body) or f"تحويل الحبوب اترفض ({status})")

    def my_military_op(self):
        """GET /military-ops/my — العملية العسكرية النشطة دلوقتي وهل الحساب منضم ولا لأ."""
        data = self.get("/military-ops/my")
        if not isinstance(data, dict):
            return None
        return data

    def join_military_op(self, op_id):
        """POST /military-ops/{op_id}/join — انضمام للعملية."""
        status, body = self.post(f"/military-ops/{op_id}/join", {})
        if status in (200, 201):
            return body
        raise GameError(_message_of(body) or f"الانضمام للعملية اترفض ({status})")

    def travel(self, destination):
        status, body = self.post("/provinces/travel/start", {"destination": destination})
        if status in (200, 201):
            return body
        raise GameError(_message_of(body) or f"السفر اترفض ({status})")

    def upgrade_skill(self, skill_key, currency):
        status, body = self.post("/players/skills/upgrade",
                                 {"skill": skill_key, "type": currency})
        if status in (200, 201):
            return body

        message = _message_of(body)
        haystack = f"{message} {body}".lower()

        if any(h in haystack for h in _ALREADY_UPGRADING_HINTS):
            remaining_ms = body.get("remaining_ms", 0) if isinstance(body, dict) else 0
            remaining_s = max(60, int(remaining_ms / 1000)) if remaining_ms else 60
            raise AlreadyUpgrading(message or "فيه ترقية شغّالة بالفعل", remaining_s)

        if any(h in haystack for h in _RATE_LIMIT_HINTS):
            retry_after = body.get("retryAfter", 65) if isinstance(body, dict) else 65
            raise RateLimited(message or "طلبات كتير بسرعة", retry_after)

        raise GameError(message or f"الترقية اترفضت ({status})")

    def toggle_auto_skill(self, skill_key, currency):
        status, body = self.post("/players/skills/auto/toggle",
                                 {"skill": skill_key, "type": currency})
        if status in (200, 201):
            return body
        raise GameError(_message_of(body) or f"التطوير التلقائي اترفض ({status})")

    def toggle_work(self):
        status, body = self.post("/players/work/toggle", {})
        if status in (200, 201):
            return body
        raise GameError(_message_of(body) or f"العمل اترفض ({status})")

    def daily_quests(self):
        data = self.get("/quests/daily")
        return data.get("quests", []) if isinstance(data, dict) else []

    def claim_quest(self, quest_key):
        status, body = self.post("/quests/claim", {"quest": quest_key})
        if status in (200, 201):
            return body
        raise GameError(_message_of(body) or "المكافأة مش متاحة")

    def wheel_state(self):
        return self.get("/wheel/state")

    def spin_wheel(self):
        status, body = self.post("/wheel/spin", {"confirm_paid": False})
        if status in (200, 201):
            return body
        raise GameError(_message_of(body) or "العجلة مش جاهزة")

    def check_ip(self):
        r = self.session.get("https://api.ipify.org?format=json",
                             proxies=self.proxies, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json().get("ip", "?")


_LOCATION_KEYS = ["location", "location_name", "city", "city_name",
                  "current_location", "province", "province_name", "residence_province"]
_NATION_KEYS = ["nation", "nation_name", "country", "country_name", "state_name"]


def _pick(profile, keys):
    for k in keys:
        v = profile.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            name = v.get("name") or v.get("title")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return ""


def parse_profile(profile):
    """بيحوّل رد البروفايل الخام لشكل ثابت نخزّنه في القاعدة."""
    skills = profile.get("skills", {}) or {}
    progress = profile.get("levelProgress", {}) or {}
    pct = progress.get("percentage", 0)
    if isinstance(pct, float) and pct <= 1:
        pct = round(pct * 100)
    else:
        try:
            pct = round(float(pct))
        except (TypeError, ValueError):
            pct = 0

    def level_of(key):
        current = skills.get(key, "?")
        pending = skills.get(f"{key}_pending")
        if pending and pending != current:
            return f"{current}←{pending}"
        return str(current)

    balance = profile.get("balance", 0)
    try:
        balance_txt = f"{int(balance):,}"
    except (TypeError, ValueError):
        balance_txt = str(balance)

    return {
        "game_name": profile.get("username", "") or "",
        "avatar_url": profile.get("avatar_url", "") or "",
        "level_num": str(profile.get("level", "—")),
        "xp_pct": max(0, min(100, pct)),
        "balance": balance_txt,
        "diamonds": str(profile.get("diamonds", "—")),
        "location": _pick(profile, _LOCATION_KEYS),
        "nation": _pick(profile, _NATION_KEYS),
        "lv_barracks": level_of("kisla"),
        "lv_war": level_of("savas_teknikleri"),
        "lv_scientist": level_of("bilim_insani"),
        "lv_supply": level_of("ikmal_talim"),
    }


# ==============================================================================
#  [٤] محرّك المهام
# ==============================================================================
#  أي أمر بيتحوّل لمهمة في جدول tasks بموعد تنفيذ. يعني:
#    • الأوامر الجماعية بتتوزّع على وقت بدل ما تتنفذ كلها في نفس اللحظة.
#    • لو السيرفر نام، المهام بتفضل مستنية في القاعدة وتتنفذ لما يرجع.
#    • إضافة ميزة = دالة واحدة + سطر في HANDLERS.
# ==============================================================================

_tick_lock = threading.Lock()


def get_account(account_id):
    return db_one("SELECT * FROM accounts WHERE id=%s", (account_id,))


def list_accounts():
    return db_all("SELECT * FROM accounts ORDER BY sort_order, id")


def client_for(account):
    return GameClient(account["token"], proxies=build_proxies(account))


def account_title(account):
    return account.get("label") or account.get("game_name") or f"حساب #{account['id']}"


def mark_error(account, message):
    db_execute("UPDATE accounts SET status='error', last_error=%s WHERE id=%s",
               (str(message)[:300], account["id"]))
    add_log(message, "error", account["id"])


def mark_ok(account, message=None):
    db_execute(
        "UPDATE accounts SET status='ok', last_error='', last_seen=NOW() WHERE id=%s",
        (account["id"],))
    if message:
        add_log(message, "ok", account["id"])


def queue_task(account_id, kind, payload=None, delay_seconds=0):
    run_at = now() + timedelta(seconds=max(0, delay_seconds))
    return db_execute(
        "INSERT INTO tasks (account_id, kind, payload, run_at) "
        "VALUES (%s,%s,%s::jsonb,%s) RETURNING id",
        (account_id, kind, json.dumps(payload or {}), run_at), returning=True)


def queue_group(account_ids, kind, payload=None, spread=True):
    """نفس الأمر على مجموعة حسابات مع فرق زمني عشوائي بينهم."""
    delay = 0
    created = 0
    for account_id in account_ids:
        queue_task(account_id, kind, payload, delay_seconds=delay)
        created += 1
        if spread:
            delay += random.randint(GROUP_SPREAD_MIN, GROUP_SPREAD_MAX)
    return created, delay


def _parse_time(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, OSError):
        return None


# ── منفّذو المهام ────────────────────────────────────────
def task_refresh(account, payload):
    data = parse_profile(client_for(account).profile())

    # لو الموقع الجديد بقى هو نفسه الوجهة اللي كان مسافر ليها، يبقى وصل
    clear_travel = (
        account.get("travel_destination")
        and data["location"]
        and data["location"].strip().lower() == account["travel_destination"].strip().lower()
    )
    extra_sets = ", travel_destination='', travel_sent_at=NULL" if clear_travel else ""

    db_execute(
        f"""UPDATE accounts SET
             game_name=%s, avatar_url=%s, level_num=%s, xp_pct=%s, balance=%s, diamonds=%s,
             location=%s, nation=%s, lv_barracks=%s, lv_war=%s,
             lv_scientist=%s, lv_supply=%s,
             status='ok', last_error='', last_seen=NOW(){extra_sets}
           WHERE id=%s""",
        (data["game_name"], data["avatar_url"], data["level_num"], data["xp_pct"],
         data["balance"], data["diamonds"], data["location"], data["nation"],
         data["lv_barracks"], data["lv_war"], data["lv_scientist"], data["lv_supply"],
         account["id"]))
    return f"البيانات اتحدّثت — المستوى {data['level_num']}"


def task_travel(account, payload):
    destination = payload.get("destination")
    if not destination:
        raise GameError("مفيش وجهة محددة")
    client_for(account).travel(destination)
    db_execute(
        "UPDATE accounts SET travel_destination=%s, travel_sent_at=NOW() WHERE id=%s",
        (destination, account["id"]))
    return f"طلب السفر إلى {destination} اترسل"


def task_visa(account, payload):
    country_id = payload.get("country_id")
    country_name = payload.get("country_name", "")
    if not country_id:
        raise GameError("مفيش دولة محددة")
    client_for(account).apply_visa(country_id)
    return f"طلب فيزا لـ {country_name}" if country_name else "طلب الفيزا اترسل"


def task_residence(account, payload):
    country_id = payload.get("country_id")
    country_name = payload.get("country_name", "")
    if not country_id:
        raise GameError("مفيش دولة محددة")
    client_for(account).apply_residence(country_id)
    return f"طلب إقامة لـ {country_name}" if country_name else "طلب الإقامة اترسل"


def task_upgrade(account, payload):
    perk = payload.get("perk") or account["perk"]
    currency = payload.get("currency") or account["currency"]
    skill_key = PERK_KEYS.get(perk)
    if not skill_key:
        raise GameError(f"مهارة غير معروفة: {perk}")
    client_for(account).upgrade_skill(skill_key, currency)
    return f"ترقية {PERKS[perk]['label']} بدأت"


def task_auto_upgrade(account, payload):
    """التطوير التلقائي بتاع اللعبة نفسها — بيشتغل ٢٤ ساعة وبنجدّده لوحدنا."""
    perk = payload.get("perk") or account["perk"]
    currency = payload.get("currency") or account["currency"]
    skill_key = PERK_KEYS.get(perk)
    if not skill_key:
        raise GameError(f"مهارة غير معروفة: {perk}")

    resp = client_for(account).toggle_auto_skill(skill_key, currency)
    label = PERKS[perk]["label"]

    if not resp.get("active", True):
        db_execute("UPDATE accounts SET auto_upgrade=FALSE, upgrade_until=NULL WHERE id=%s",
                   (account["id"],))
        return f"اللعبة وقّفت التطوير التلقائي ({label}) — الشرط أو الرصيد مش مكفّي"

    until = _parse_time(resp.get("until")) or (now() + timedelta(hours=24))
    db_execute("UPDATE accounts SET upgrade_until=%s, auto_upgrade=TRUE WHERE id=%s",
               (until, account["id"]))
    return f"التطوير التلقائي شغّال على {label}"


def task_quests(account, payload):
    client = client_for(account)
    claimed = 0
    for quest in client.daily_quests():
        if not isinstance(quest, dict):
            continue
        key = quest.get("key") or quest.get("id")
        if quest.get("completed") and not quest.get("claimed") and key:
            try:
                client.claim_quest(key)
                claimed += 1
            except GameError:
                continue
    return f"استلم {claimed} مكافأة مهام" if claimed else None


def task_wheel(account, payload):
    client = client_for(account)
    state = client.wheel_state()
    if not (state.get("free_available") or state.get("can_spin_free")):
        return None
    client.spin_wheel()
    return "لفّ العجلة المجانية"


def task_work(account, payload):
    resp = client_for(account).toggle_work()
    until = _parse_time(resp.get("until")) or (now() + timedelta(hours=12))
    db_execute("UPDATE accounts SET work_until=%s WHERE id=%s", (until, account["id"]))
    return "بدأ الشغل في المصنع"


def _current_diamonds(account):
    try:
        return int(str(account.get("diamonds", "0")).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0


def task_pills_auto(account, payload):
    """
    تحويل تلقائي — بيحوّل بس الماس الزايد عن الحد اللي محطوطه، وبشرط الزيادة
    تكون ١٠٠ ماسة على الأقل (عشان منزعجش اللعبة بطلبات تافهة).
    """
    limit = int(account.get("pills_limit") or 2500)
    current = _current_diamonds(account)
    excess = current - limit
    if excess < 100:
        return None  # لسه ملحقش الحد — من غير رسالة عشان منزحمش اللوج

    res = client_for(account).craft_pills(excess)
    pills = res.get("pills_crafted", excess * 5)
    remaining = res.get("diamonds_remaining", max(0, current - excess))
    db_execute("UPDATE accounts SET diamonds=%s WHERE id=%s", (str(remaining), account["id"]))
    return f"تحويل تلقائي: {excess:,} ماسة → {pills:,} حبة (باقي {remaining:,})"


def task_military_auto(account, payload):
    """
    لو فيه عملية عسكرية نشطة والحساب مش منضم (أو انضمامه هيخلص قريب)، بينضم تاني.
    اللعبة نفسها بتحدّد مدة الانضمام؛ منجدّدش قبل آخر ١٠ دقايق منها.
    """
    client = client_for(account)
    data = client.my_military_op()
    if not data:
        return None  # مفيش عملية نشطة دلوقتي

    op = data.get("operation") or {}
    op_id = op.get("id")
    if not op_id:
        return None

    joined_until = _parse_time(data.get("joined_until"))
    is_joined = bool(data.get("is_joined"))

    needs_join = True
    if joined_until:
        needs_join = now() >= (joined_until - timedelta(minutes=10))
    elif is_joined:
        needs_join = False

    if not needs_join:
        return None

    res = client.join_military_op(op_id)
    until = _parse_time(res.get("joined_until"))
    if until:
        db_execute("UPDATE accounts SET military_joined_until=%s WHERE id=%s",
                   (until, account["id"]))
        return f"انضم للعملية العسكرية — لحد {until.strftime('%H:%M')}"
    return "انضم للعملية العسكرية"


def task_plan_step(account, payload):
    """
    بينفّذ خطوة واحدة بس من خطة التطوير، وبيجدول الخطوة الجاية لوحده لما يجيله
    وقتها الحقيقي — اللعبة مسموح فيها ترقية واحدة بس شغّالة في نفس الوقت
    للحساب كله، فمفيش معنى إننا نحاول قبل الأوان.
    """
    plan = account.get("upgrade_plan")
    if not plan:
        return None  # الخطة اتلغت أو خلصت قبل كده

    steps = plan.get("steps") or []
    idx = plan.get("step_index", 0)
    if idx >= len(steps):
        db_execute("UPDATE accounts SET upgrade_plan=NULL WHERE id=%s", (account["id"],))
        return "خطة التطوير خلصت بالكامل"

    step = steps[idx]
    perk = step["perk"]
    count = step["count"]
    done_before = plan.get("done_in_step", 0)
    currency = plan.get("currency", "money")
    skill_key = PERK_KEYS.get(perk)
    label = PERKS.get(perk, {}).get("label", perk)
    client = client_for(account)

    try:
        client.upgrade_skill(skill_key, currency)
    except AlreadyUpgrading as e:
        # لسه فيه ترقية شغّالة (مش بالضرورة من الخطة — ممكن حد بدأ ترقية يدوي) —
        # منعدّش الخطوة دي فاشلة، نستنى بس ونجرب تاني بعد الوقت اللي اللعبة قالته
        queue_task(account["id"], "plan_step", delay_seconds=e.remaining_seconds)
        return None
    except RateLimited as e:
        queue_task(account["id"], "plan_step", delay_seconds=e.retry_after)
        return None

    done_after = done_before + 1
    if done_after >= count:
        next_idx, next_done = idx + 1, 0
    else:
        next_idx, next_done = idx, done_after

    if next_idx >= len(steps):
        db_execute("UPDATE accounts SET upgrade_plan=NULL WHERE id=%s", (account["id"],))
        return f"خطة التطوير خلصت بالكامل — آخر خطوة: {label} ({done_after}/{count})"

    plan["step_index"], plan["done_in_step"] = next_idx, next_done
    db_execute("UPDATE accounts SET upgrade_plan=%s::jsonb WHERE id=%s",
              (json.dumps(plan), account["id"]))

    # نجيب الوقت الحقيقي من بروفايل محدّث بدل ما نخمّن
    try:
        wait_s = skill_cooldown_seconds(client.profile()) or 65
    except Exception:
        wait_s = 65
    queue_task(account["id"], "plan_step", delay_seconds=wait_s)

    return f"ترقية {label} ({done_after}/{count})"


HANDLERS = {
    "refresh": task_refresh,
    "travel": task_travel,
    "visa": task_visa,
    "residence": task_residence,
    "upgrade": task_upgrade,
    "auto_upgrade": task_auto_upgrade,
    "quests": task_quests,
    "wheel": task_wheel,
    "work": task_work,
    "pills_auto": task_pills_auto,
    "military_auto": task_military_auto,
    "plan_step": task_plan_step,
}

KIND_LABELS = {
    "refresh": "تحديث", "travel": "سفر", "visa": "طلب فيزا", "residence": "طلب إقامة",
    "upgrade": "ترقية", "auto_upgrade": "تطوير تلقائي", "quests": "مهام يومية",
    "wheel": "عجلة", "work": "شغل", "pills_auto": "تحويل حبوب تلقائي",
    "military_auto": "انضمام عسكري", "plan_step": "خطوة من خطة تطوير",
}


def run_task(task):
    account = get_account(task["account_id"])
    if not account:
        db_execute("UPDATE tasks SET status='cancelled', result=%s WHERE id=%s",
                   ("الحساب اتمسح", task["id"]))
        return

    if not account["token"]:
        db_execute("UPDATE tasks SET status='failed', result=%s WHERE id=%s",
                   ("مفيش توكن للحساب", task["id"]))
        mark_error(account, "المهمة اتوقفت — الحساب من غير توكن")
        return

    handler = HANDLERS.get(task["kind"])
    if not handler:
        db_execute("UPDATE tasks SET status='failed', result=%s WHERE id=%s",
                   (f"نوع مهمة مش معروف: {task['kind']}", task["id"]))
        return

    title = account_title(account)
    try:
        message = handler(account, task["payload"] or {})
        db_execute(
            "UPDATE tasks SET status='done', result=%s, attempts=attempts+1 WHERE id=%s",
            ((message or "تم")[:300], task["id"]))
        mark_ok(account, f"{title}: {message}" if message else None)

    except TokenInvalid as e:
        db_execute(
            "UPDATE tasks SET status='failed', result=%s, attempts=attempts+1 WHERE id=%s",
            (str(e), task["id"]))
        db_execute("UPDATE accounts SET enabled=FALSE, auto_upgrade=FALSE WHERE id=%s",
                   (account["id"],))
        mark_error(account, f"{title}: التوكن مرفوض — الحساب اتوقّف لحد ما تجدّده")

    except GameError as e:
        attempts = task["attempts"] + 1
        if attempts < 3:
            db_execute("UPDATE tasks SET attempts=%s, run_at=%s, result=%s WHERE id=%s",
                       (attempts, now() + timedelta(minutes=5 * attempts),
                        str(e)[:300], task["id"]))
            add_log(f"{title}: {e} — هنعيد المحاولة", "warn", account["id"])
        else:
            db_execute("UPDATE tasks SET status='failed', attempts=%s, result=%s WHERE id=%s",
                       (attempts, str(e)[:300], task["id"]))
            mark_error(account, f"{title}: {e}")

    except Exception as e:
        log.exception("خطأ غير متوقع في المهمة %s", task["id"])
        db_execute(
            "UPDATE tasks SET status='failed', attempts=attempts+1, result=%s WHERE id=%s",
            (f"{type(e).__name__}: {e}"[:300], task["id"]))
        mark_error(account, f"{title}: خطأ داخلي — {type(e).__name__}")


def _queue_if_free(account_id, kind, min_gap_minutes=0):
    if db_one("SELECT id FROM tasks WHERE account_id=%s AND kind=%s AND status='pending' LIMIT 1",
              (account_id, kind)):
        return False
    if min_gap_minutes:
        if db_one("SELECT id FROM tasks WHERE account_id=%s AND kind=%s AND status='done' "
                  "AND created_at > %s LIMIT 1",
                  (account_id, kind, now() - timedelta(minutes=min_gap_minutes))):
            return False
    queue_task(account_id, kind, delay_seconds=random.randint(0, 45))
    return True


def schedule_periodic():
    """بيبص على الحسابات المفعّلة ويضيف المهام اللي حان وقتها."""
    accounts = db_all("SELECT * FROM accounts WHERE enabled=TRUE AND token<>''")
    added = 0
    stale_before = now() - timedelta(minutes=PROFILE_REFRESH_MIN)

    for account in accounts:
        aid = account["id"]

        last_seen = account.get("last_seen")
        if (last_seen is None or last_seen < stale_before) and _queue_if_free(aid, "refresh"):
            added += 1

        if account.get("auto_upgrade"):
            until = account.get("upgrade_until")
            if (until is None or until <= now() + timedelta(minutes=5)) \
                    and _queue_if_free(aid, "auto_upgrade"):
                added += 1

        if account.get("auto_quests") and _queue_if_free(aid, "quests", 60):
            added += 1

        if account.get("auto_wheel") and _queue_if_free(aid, "wheel", 60):
            added += 1

        if account.get("auto_work"):
            work_until = account.get("work_until")
            if (work_until is None or work_until <= now()) and _queue_if_free(aid, "work"):
                added += 1

        if account.get("auto_pills") and _queue_if_free(aid, "pills_auto", min_gap_minutes=5):
            added += 1

        if account.get("auto_military") and _queue_if_free(aid, "military_auto", min_gap_minutes=120):
            added += 1

    # لو عدّت ساعة من غير ما نتأكد إن الحساب وصل، بنشيل شارة "بيسافر" —
    # يمكن اللعبة رفضت السفر أو الرحلة خلصت وإحنا فاتنا التحديث اللي أكّد كده
    stale_travel = now() - timedelta(minutes=TRAVEL_TIMEOUT_MINUTES)
    db_execute(
        "UPDATE accounts SET travel_destination='', travel_sent_at=NULL "
        "WHERE travel_sent_at IS NOT NULL AND travel_sent_at < %s",
        (stale_travel,))

    # شبكة أمان لخطط التطوير: لو حساب عنده خطة شغّالة بس مفيش مهمة plan_step
    # منتظرة ليه (مثلاً فشلت ٣ مرات وانقطعت السلسلة)، نرجّع نجدولها —
    # الخطة دي مستقلة عن مفتاح "تشغيل/إيقاف" الحساب، فبنشتغل حتى لو موقوف
    planning = db_all(
        "SELECT id FROM accounts WHERE upgrade_plan IS NOT NULL AND token<>''")
    for account in planning:
        if _queue_if_free(account["id"], "plan_step"):
            added += 1

    return added


def _cleanup():
    try:
        db_execute("DELETE FROM tasks WHERE status IN ('done','failed','cancelled') "
                   "AND created_at < %s", (now() - timedelta(days=2),))
        trim_logs()
    except Exception as e:
        log.error("التنظيف فشل: %s", e)


def run_tick(source="scheduler"):
    """نبضة التشغيل — محميّة بقفل عشان متشتغلش مرتين في نفس الوقت."""
    if not _tick_lock.acquire(blocking=False):
        return {"skipped": True, "reason": "فيه نبضة شغالة بالفعل"}

    started = now()
    try:
        try:
            init_db()
        except Exception as e:
            return {"ok": False, "error": f"القاعدة مش راضية ترد: {e}"}

        scheduled = schedule_periodic()
        due = db_all("SELECT * FROM tasks WHERE status='pending' AND run_at <= NOW() "
                     "ORDER BY run_at LIMIT %s", (MAX_TASKS_PER_TICK,))
        for task in due:
            run_task(task)

        _cleanup()
        return {"ok": True, "source": source, "scheduled": scheduled,
                "executed": len(due),
                "seconds": round((now() - started).total_seconds(), 2)}
    except Exception as e:
        log.exception("النبضة فشلت")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        _tick_lock.release()


# ==============================================================================
#  [٥] التصميم وكود الواجهة
# ==============================================================================
#  الأحمر والأخضر من علم المغرب، بس كإشارة مش كخلفية:
#  الأحمر = الهوية والأزرار، الأخضر = الحساب شغّال.
# ==============================================================================

CSS = r"""
:root {
  --bg:#0E1116; --bg-raise:#151A21; --panel:#171D25; --panel-2:#1E252F;
  --line:#262E39; --line-soft:#1F2731;
  --red:#C1272D; --red-bright:#E5484D; --red-dim:rgba(193,39,45,.14);
  --green:#00713F; --green-bright:#25A35F; --green-dim:rgba(37,163,95,.13);
  --sand:#D9A441; --text:#E8EBF0; --text-soft:#A7B0BD; --muted:#6B7684;
  --r-sm:8px; --r-md:12px; --r-lg:16px;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.28);
  --font-display:"Reem Kufi",system-ui,sans-serif;
  --font-body:"Tajawal",system-ui,sans-serif;
  --font-mono:"JetBrains Mono",ui-monospace,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--text);
  font-family:var(--font-body);font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased}
body::before{content:"";position:fixed;inset:0 0 auto 0;height:320px;
  background:radial-gradient(ellipse 70% 100% at 50% 0%,rgba(193,39,45,.16),transparent 70%);
  pointer-events:none;z-index:0}
a{color:var(--red-bright)}
button,input,select,textarea{font-family:inherit;font-size:inherit;color:inherit}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:var(--line);border-radius:4px}
.wrap{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding:0 14px 120px}

.topbar{display:flex;align-items:center;gap:12px;padding:18px 0 14px;
  border-bottom:1px solid var(--line-soft);margin-bottom:18px}
.brand{display:flex;align-items:center;gap:10px}
.brand-mark{width:34px;height:34px;flex-shrink:0}
.brand-mark polygon{fill:none;stroke:var(--green-bright);stroke-width:6;stroke-linejoin:round}
.brand-name{font-family:var(--font-display);font-size:19px;letter-spacing:.3px;margin:0}
.brand-sub{font-size:11px;color:var(--muted);margin:-4px 0 0;letter-spacing:.4px}
.topbar-spacer{flex:1}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:baseline;gap:5px;padding:5px 10px;background:var(--panel);
  border:1px solid var(--line);border-radius:999px;font-size:11px;color:var(--text-soft);white-space:nowrap}
.chip b{font-family:var(--font-mono);font-size:13px;color:var(--text);font-weight:500}
.chip.on b{color:var(--green-bright)}
.chip.bad b{color:var(--red-bright)}
.chip.wait b{color:var(--sand)}

.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 15px;
  border-radius:var(--r-sm);border:1px solid var(--line);background:var(--panel-2);color:var(--text);
  cursor:pointer;font-size:13.5px;font-weight:500;
  transition:background .15s,border-color .15s,transform .08s}
.btn:hover:not(:disabled){background:#262F3B;border-color:#333D4A}
.btn:active:not(:disabled){transform:translateY(1px)}
.btn:disabled{opacity:.42;cursor:not-allowed}
.btn:focus-visible{outline:2px solid var(--red-bright);outline-offset:2px}
.btn-primary{background:var(--red);border-color:var(--red);color:#fff}
.btn-primary:hover:not(:disabled){background:var(--red-bright);border-color:var(--red-bright)}
.btn-go{background:var(--green);border-color:var(--green);color:#fff}
.btn-go:hover:not(:disabled){background:var(--green-bright);border-color:var(--green-bright)}
.btn-ghost{background:transparent}
.btn-danger{color:var(--red-bright);border-color:rgba(229,72,77,.3);background:var(--red-dim)}
.btn-sm{padding:6px 10px;font-size:12px}

.command-bar{position:sticky;top:0;z-index:40;background:rgba(14,17,22,.92);
  backdrop-filter:blur(12px);border:1px solid var(--line);border-radius:var(--r-md);
  padding:12px;margin-bottom:18px;box-shadow:var(--shadow)}
.command-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.command-count{font-family:var(--font-mono);font-size:12px;color:var(--sand);padding:4px 9px;
  border:1px dashed rgba(217,164,65,.35);border-radius:var(--r-sm);white-space:nowrap}
.field{background:var(--bg-raise);border:1px solid var(--line);border-radius:var(--r-sm);
  padding:8px 11px;color:var(--text);min-width:0}
.field:focus{outline:none;border-color:var(--red)}
select.field{cursor:pointer}

.section-head{display:flex;align-items:center;gap:10px;margin:26px 0 12px}
.section-head h2{font-family:var(--font-display);font-size:15px;font-weight:400;margin:0;
  color:var(--text-soft);letter-spacing:.5px}
.section-head .rule{flex:1;height:1px;background:var(--line-soft)}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(310px,1fr))}

.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);
  padding:14px;transition:border-color .18s}
.card.selected{border-color:var(--red);box-shadow:0 0 0 1px var(--red-dim)}
.card.is-error{border-color:rgba(229,72,77,.4)}
.card-head{display:flex;align-items:flex-start;gap:10px}
.avatar-wrap{position:relative;width:38px;height:38px;flex-shrink:0}
.avatar-img{width:100%;height:100%;object-fit:cover;border-radius:50%;
  border:1px solid var(--line-soft);display:block;background:var(--bg-raise)}
.avatar-fallback{width:100%;height:100%;border-radius:50%;background:var(--bg-raise);
  border:1px solid var(--line-soft);display:flex;align-items:center;justify-content:center;font-size:17px}
.status-star{position:absolute;bottom:-4px;left:-4px;width:16px;height:16px;
  background:var(--panel);border-radius:50%}
.status-star polygon{fill:none;stroke:var(--muted);stroke-width:9;stroke-linejoin:round;
  transition:stroke .25s}
.card.is-running .status-star polygon{stroke:var(--green-bright);
  filter:drop-shadow(0 0 5px rgba(37,163,95,.5))}
.card.is-error .status-star polygon{stroke:var(--red-bright)}
.card-title{flex:1;min-width:0}
.card-title h3{margin:0;font-size:15px;font-weight:700;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.card-title .sub{font-size:11.5px;color:var(--muted);display:flex;gap:6px;align-items:center;
  flex-wrap:wrap}
.squad-tag{font-size:10.5px;padding:1px 7px;border-radius:999px;background:var(--green-dim);
  color:var(--green-bright);border:1px solid rgba(37,163,95,.22)}
.pick{width:19px;height:19px;accent-color:var(--red);cursor:pointer;flex-shrink:0;margin-top:4px}
.err-line{margin-top:9px;font-size:12px;color:var(--red-bright);background:var(--red-dim);
  border-right:2px solid var(--red);padding:6px 9px;border-radius:0 var(--r-sm) var(--r-sm) 0}
.travel-badge{margin-top:9px;font-size:12px;color:var(--sand);background:rgba(217,164,65,.12);
  border-right:2px solid var(--sand);padding:6px 9px;border-radius:0 var(--r-sm) var(--r-sm) 0}
.plan-badge{margin-top:9px;font-size:12px;color:var(--green-bright);background:var(--green-dim);
  border-right:2px solid var(--green-bright);padding:6px 9px;border-radius:0 var(--r-sm) var(--r-sm) 0;
  display:flex;align-items:center;gap:8px}
.plan-badge .txt{flex:1}

.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line-soft);
  border-radius:var(--r-sm);overflow:hidden;margin:12px 0 10px}
.stat{background:var(--bg-raise);padding:8px 9px}
.stat .k{font-size:10px;color:var(--muted);display:block}
.stat .v{font-family:var(--font-mono);font-size:13px;color:var(--text);display:block;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat .v.gold{color:var(--sand)}
.xp-track{height:3px;background:var(--line-soft);border-radius:2px;overflow:hidden;margin-top:5px}
.xp-fill{height:100%;background:var(--green-bright)}

.skills{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
.skill{flex:1;min-width:62px;text-align:center;background:var(--bg-raise);
  border:1px solid var(--line-soft);border-radius:var(--r-sm);padding:5px 3px}
.skill .k{font-size:9.5px;color:var(--muted);display:block}
.skill .v{font-family:var(--font-mono);font-size:12.5px}
.skill.active{border-color:rgba(217,164,65,.4)}
.skill.active .v{color:var(--sand)}

.toggles{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px}
.toggle{display:flex;align-items:center;gap:7px;padding:7px 9px;background:var(--bg-raise);
  border:1px solid var(--line-soft);border-radius:var(--r-sm);cursor:pointer;font-size:12px;
  user-select:none}
.toggle input{accent-color:var(--green-bright);width:15px;height:15px;cursor:pointer;margin:0}
.toggle.on{border-color:rgba(37,163,95,.35);color:var(--green-bright)}
.selects{display:flex;gap:6px;margin-bottom:10px}
.selects .field{flex:1;font-size:12.5px;padding:7px 9px}

.proxy-line{display:flex;align-items:center;gap:7px;font-size:12px;padding:8px 10px;
  background:var(--bg-raise);border:1px solid var(--line-soft);border-radius:var(--r-sm);
  margin-bottom:10px}
.proxy-line .dot{width:7px;height:7px;border-radius:50%;background:var(--muted);flex-shrink:0}
.proxy-line.set .dot{background:var(--green-bright)}
.proxy-line .txt{flex:1;font-family:var(--font-mono);font-size:11.5px;color:var(--text-soft);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card-actions{display:flex;gap:6px;flex-wrap:wrap}

.log{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);
  max-height:340px;overflow-y:auto}
.log-row{display:flex;gap:10px;padding:8px 12px;border-bottom:1px solid var(--line-soft);
  font-size:12.5px}
.log-row:last-child{border-bottom:none}
.log-row time{font-family:var(--font-mono);font-size:11px;color:var(--muted);flex-shrink:0}
.log-row .msg{flex:1}
.log-row.ok .msg{color:var(--green-bright)}
.log-row.error .msg{color:var(--red-bright)}
.log-row.warn .msg{color:var(--sand)}

.empty{text-align:center;padding:46px 20px;border:1px dashed var(--line);
  border-radius:var(--r-md);color:var(--muted)}
.empty h3{font-family:var(--font-display);font-weight:400;color:var(--text-soft);margin:0 0 6px}
.empty p{margin:0 0 16px;font-size:13px}

.overlay{position:fixed;inset:0;background:rgba(6,8,11,.76);backdrop-filter:blur(3px);
  display:none;align-items:center;justify-content:center;padding:16px;z-index:100}
.overlay.open{display:flex}
.modal{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-lg);
  width:100%;max-width:460px;max-height:88vh;overflow-y:auto;box-shadow:var(--shadow)}
.modal-head{padding:15px 18px;border-bottom:1px solid var(--line-soft);display:flex;
  align-items:center;gap:10px}
.modal-head h3{font-family:var(--font-display);font-weight:400;margin:0;font-size:16px;flex:1}
.modal-body{padding:16px 18px}
.modal-foot{padding:13px 18px;border-top:1px solid var(--line-soft);display:flex;gap:8px;
  justify-content:flex-start}
.form-row{margin-bottom:13px}
.form-row label{display:block;font-size:12px;color:var(--text-soft);margin-bottom:5px}
.form-row .field{width:100%}
.form-row .hint,.hint{font-size:11px;color:var(--muted);margin-top:4px}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}

.province-list{max-height:260px;overflow-y:auto;border:1px solid var(--line);
  border-radius:var(--r-sm);margin-top:8px}
.province{padding:9px 12px;border-bottom:1px solid var(--line-soft);cursor:pointer;font-size:13px}
.province:last-child{border-bottom:none}
.province:hover{background:var(--panel-2)}
.province.picked{background:var(--red-dim);color:var(--red-bright)}

.toast-stack{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);z-index:200;
  display:flex;flex-direction:column;gap:8px;width:calc(100% - 32px);max-width:400px}
.toast{background:var(--panel-2);border:1px solid var(--line);
  border-right:3px solid var(--green-bright);border-radius:var(--r-sm);padding:11px 14px;
  font-size:13px;box-shadow:var(--shadow);animation:rise .22s ease-out}
.toast.err{border-right-color:var(--red-bright)}
@keyframes rise{from{opacity:0;transform:translateY(10px)}}

.login-page{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.login-box{width:100%;max-width:340px;background:var(--panel);border:1px solid var(--line);
  border-radius:var(--r-lg);padding:30px 26px;box-shadow:var(--shadow)}
.login-box .brand-mark{width:46px;height:46px;margin:0 auto 14px;display:block}
.login-box h1{font-family:var(--font-display);font-weight:400;font-size:20px;text-align:center;
  margin:0 0 24px}
.login-box .btn{width:100%;margin-top:6px}
.login-err{background:var(--red-dim);border:1px solid rgba(229,72,77,.28);color:var(--red-bright);
  border-radius:var(--r-sm);padding:9px 12px;font-size:12.5px;margin-bottom:16px}

@media (max-width:560px){
  .grid{grid-template-columns:1fr}
  .form-grid{grid-template-columns:1fr}
  .brand-sub{display:none}
  .command-bar{padding:10px}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.01ms !important;transition-duration:.01ms !important}
}
"""

JS = r"""
const STAR = '<polygon points="50,5 76.4,86.4 7.2,36.1 92.8,36.1 23.6,86.4"/>';

const state = {
  accounts: [], logs: [], squads: [],
  selected: new Set(), squadFilter: '',
  countries: [], expandedCountry: null,
  planSteps: [],
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  let body = {};
  try { body = await res.json(); } catch (_) {}
  if (!res.ok || body.ok === false) {
    throw new Error(body.error || `الطلب فشل (${res.status})`);
  }
  return body;
}

function toast(message, isError = false) {
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' err' : '');
  el.textContent = message;
  $('toasts').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

async function loadState() {
  try {
    const data = await api('/api/state');
    state.accounts = data.accounts;
    state.logs = data.logs;
    state.squads = data.squads;
    const alive = new Set(state.accounts.map((a) => a.id));
    state.selected.forEach((id) => { if (!alive.has(id)) state.selected.delete(id); });
    renderChips(data.summary);
    renderSquadOptions();
    renderAccounts();
    renderLog();
    renderPickState();
  } catch (e) {
    if (String(e.message).includes('تسجّل دخول')) location.href = '/login';
  }
}

function renderChips(s) {
  $('chips').innerHTML = `
    <span class="chip">الحسابات <b>${s.total}</b></span>
    <span class="chip on">شغّال <b>${s.running}</b></span>
    ${s.errors ? `<span class="chip bad">أخطاء <b>${s.errors}</b></span>` : ''}
    ${s.pending_tasks ? `<span class="chip wait">في الطابور <b>${s.pending_tasks}</b></span>` : ''}
  `;
}

function renderSquadOptions() {
  const select = $('squad-filter');
  const current = state.squadFilter;
  select.innerHTML = '<option value="">كل المجموعات</option>' +
    state.squads.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
  select.value = current;
  $('squad-options').innerHTML = state.squads.map((s) => `<option value="${esc(s)}">`).join('');
}

function visibleAccounts() {
  if (!state.squadFilter) return state.accounts;
  return state.accounts.filter((a) => a.squad === state.squadFilter);
}

function renderAccounts() {
  const list = visibleAccounts();
  const host = $('accounts');
  if (!list.length) {
    host.innerHTML = `
      <div class="empty">
        <h3>مفيش حسابات لسه</h3>
        <p>ضيف أول حساب بالتوكن بتاعه، وبعدها تقدر تتحكم فيهم كلهم مع بعض.</p>
        <button class="btn btn-primary" onclick="openAccountModal()">إضافة حساب</button>
      </div>`;
    return;
  }
  host.innerHTML = `<div class="grid">${list.map(cardHtml).join('')}</div>`;
}

function cardHtml(a) {
  const classes = ['card'];
  if (state.selected.has(a.id)) classes.push('selected');
  if (a.enabled && a.status !== 'error') classes.push('is-running');
  if (a.status === 'error') classes.push('is-error');

  const skill = (key, label) => `
    <div class="skill ${a.perk === key ? 'active' : ''}">
      <span class="k">${label}</span>
      <span class="v">${esc(a.skills[key])}</span>
    </div>`;

  const toggle = (field, label) => `
    <label class="toggle ${a[field] ? 'on' : ''}">
      <input type="checkbox" ${a[field] ? 'checked' : ''}
             onchange="patchAccount(${a.id}, {${field}: this.checked})">
      <span>${label}</span>
    </label>`;

  const proxyText = a.proxy.configured
    ? `${esc(a.proxy.line_masked)}${a.proxy.note ? ' — ' + esc(a.proxy.note) : ''}`
    : 'مفيش بروكسي — الطلبات هتخرج من السيرفر مباشرة';

  return `
  <div class="${classes.join(' ')}">
    <div class="card-head">
      <input class="pick" type="checkbox" ${state.selected.has(a.id) ? 'checked' : ''}
             onchange="togglePick(${a.id}, this.checked)" aria-label="اختيار ${esc(a.label)}">
      <div class="avatar-wrap">
        ${a.avatar_url
          ? `<img class="avatar-img" src="${esc(a.avatar_url)}" alt=""
                 onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'avatar-fallback',textContent:'🎮'}))">`
          : `<div class="avatar-fallback">🎮</div>`}
        <svg class="status-star" viewBox="0 0 100 100" aria-hidden="true">${STAR}</svg>
      </div>
      <div class="card-title">
        <h3>${esc(a.label || 'بدون اسم')}</h3>
        <div class="sub">
          ${a.game_name ? esc(a.game_name) : 'لسه مجابش بيانات'}
          <span class="squad-tag">${esc(a.squad)}</span>
          ${a.has_token ? '' : '<span style="color:var(--red-bright)">مفيش توكن</span>'}
        </div>
      </div>
    </div>

    ${a.last_error ? `<div class="err-line">${esc(a.last_error)}</div>` : ''}
    ${a.travel ? `<div class="travel-badge">🚀 مسافر إلى ${esc(a.travel.destination)}${travelElapsed(a.travel.sent_at)}</div>` : ''}
    ${a.upgrade_plan ? `<div class="plan-badge">
      <span class="txt">📋 خطة تطوير: خطوة ${a.upgrade_plan.step_index}/${a.upgrade_plan.total_steps} —
      ${esc(a.upgrade_plan.current_label)} (${a.upgrade_plan.done_in_step}/${a.upgrade_plan.step_count}) ·
      باقي ${a.upgrade_plan.total_remaining} إجمالاً</span>
      <button class="btn btn-sm btn-ghost" onclick="cancelPlan(${a.id})">إلغاء</button>
    </div>` : ''}

    <div class="stats">
      <div class="stat">
        <span class="k">المستوى</span>
        <span class="v gold">${esc(a.level_num)}</span>
        <div class="xp-track"><div class="xp-fill" style="width:${a.xp_pct}%"></div></div>
      </div>
      <div class="stat"><span class="k">الرصيد</span><span class="v">${esc(a.balance)}</span></div>
      <div class="stat"><span class="k">الماس</span><span class="v gold">${esc(a.diamonds)}</span></div>
    </div>

    <div class="stats" style="grid-template-columns:1fr">
      <div class="stat">
        <span class="k">الموقع الحالي</span>
        <span class="v">${esc(a.location || '—')}${a.nation ? ' · ' + esc(a.nation) : ''}</span>
      </div>
    </div>

    <div class="skills" style="margin-top:10px">
      ${skill('barracks', 'ثكنات')}
      ${skill('war_techniques', 'حرب')}
      ${skill('scientist', 'علم')}
      ${skill('supply_drill', 'إمداد')}
    </div>

    <div class="selects">
      <select class="field" onchange="patchAccount(${a.id}, {perk: this.value})">
        ${Object.entries(window.PERKS).map(([k, v]) =>
          `<option value="${k}" ${a.perk === k ? 'selected' : ''}>${esc(v.label)}</option>`).join('')}
      </select>
      <select class="field" onchange="patchAccount(${a.id}, {currency: this.value})">
        ${Object.entries(window.CURRENCIES).map(([k, v]) =>
          `<option value="${k}" ${a.currency === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}
      </select>
    </div>

    <div class="toggles">
      ${toggle('auto_upgrade', 'تطوير تلقائي')}
      ${toggle('auto_quests', 'مهام يومية')}
      ${toggle('auto_wheel', 'العجلة')}
      ${toggle('auto_work', 'الشغل')}
      ${toggle('auto_military', 'عملية عسكرية')}
    </div>

    <div class="proxy-line ${a.auto_pills ? 'set' : ''}" style="gap:6px">
      <span class="dot"></span>
      <label class="toggle ${a.auto_pills ? 'on' : ''}" style="padding:0;border:none;background:none;flex-shrink:0">
        <input type="checkbox" ${a.auto_pills ? 'checked' : ''}
               onchange="patchAccount(${a.id}, {auto_pills: this.checked})">
        <span>حبوب تلقائي</span>
      </label>
      <span style="font-size:11px;color:var(--muted)">فوق</span>
      <input class="field" type="number" min="0" value="${a.pills_limit}" style="width:80px;padding:5px 7px;font-size:11.5px"
             onchange="patchAccount(${a.id}, {pills_limit: parseInt(this.value)||0})">
      <span style="font-size:11px;color:var(--muted)">ماسة</span>
    </div>

    <div class="proxy-line ${a.proxy.configured ? 'set' : ''}">
      <span class="dot"></span>
      <span class="txt">${proxyText}</span>
      <button class="btn btn-sm btn-ghost" onclick="openProxyModal(${a.id})">تعديل</button>
    </div>

    <div class="card-actions">
      <button class="btn btn-sm ${a.enabled ? '' : 'btn-go'}"
              onclick="patchAccount(${a.id}, {enabled: ${!a.enabled}})">
        ${a.enabled ? 'إيقاف' : 'تشغيل'}
      </button>
      <button class="btn btn-sm" onclick="runOne(${a.id}, 'refresh')">تحديث</button>
      <button class="btn btn-sm" onclick="openAccountModal(${a.id})">تعديل</button>
      <button class="btn btn-sm btn-danger" onclick="removeAccount(${a.id})">حذف</button>
    </div>
  </div>`;
}

function travelElapsed(sentAt) {
  if (!sentAt) return '';
  const mins = Math.max(0, Math.round((Date.now() - new Date(sentAt).getTime()) / 60000));
  if (mins < 1) return ' (لسه دلوقتي)';
  if (mins < 60) return ` (من ${mins} دقيقة)`;
  return ` (من ${Math.round(mins / 60)} ساعة)`;
}

function togglePick(id, on) {
  if (on) state.selected.add(id); else state.selected.delete(id);
  renderAccounts();
  renderPickState();
}

function renderPickState() {
  const n = state.selected.size;
  $('pick-count').textContent = n ? `${n} مختار` : 'مفيش اختيار';
  ['btn-travel', 'btn-upgrade', 'btn-autoupgrade', 'btn-refresh', 'btn-plan']
    .forEach((id) => { $(id).disabled = n === 0; });
}

async function patchAccount(id, changes) {
  try {
    await api(`/api/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(changes) });
    await loadState();
  } catch (e) { toast(e.message, true); loadState(); }
}

async function removeAccount(id) {
  const account = state.accounts.find((a) => a.id === id);
  if (!confirm(`تمسح "${account?.label || id}"؟ ده مش هيرجع تاني.`)) return;
  try {
    await api(`/api/accounts/${id}`, { method: 'DELETE' });
    toast('الحساب اتمسح');
    await loadState();
  } catch (e) { toast(e.message, true); }
}

async function runOne(id, kind, payload = {}) {
  try {
    const r = await api('/api/command', {
      method: 'POST',
      body: JSON.stringify({ kind, account_ids: [id], payload, spread: false }),
    });
    toast(r.note);
    setTimeout(loadState, 1500);
  } catch (e) { toast(e.message, true); }
}

async function runGroup(kind, payload = {}, spread = true) {
  const ids = [...state.selected];
  if (!ids.length) return toast('اختار حسابات الأول', true);
  try {
    const r = await api('/api/command', {
      method: 'POST',
      body: JSON.stringify({ kind, account_ids: ids, payload, spread }),
    });
    toast(r.note);
    setTimeout(loadState, 1500);
  } catch (e) { toast(e.message, true); }
}

function openAccountModal(id = null) {
  const account = id ? state.accounts.find((a) => a.id === id) : null;
  $('account-modal-title').textContent = account ? 'تعديل الحساب' : 'حساب جديد';
  $('acc-id').value = account ? account.id : '';
  $('acc-label').value = account ? account.label : '';
  $('acc-squad').value = account ? account.squad : 'المجموعة الأولى';
  $('acc-token').value = '';
  $('acc-token').placeholder = account ? 'سيبه فاضي لو مش عايز تغيّره' : 'الصق التوكن هنا';
  openModal('modal-account');
}

async function saveAccount() {
  const id = $('acc-id').value;
  const payload = {
    label: $('acc-label').value.trim(),
    squad: $('acc-squad').value.trim() || 'المجموعة الأولى',
  };
  const token = $('acc-token').value.trim();
  if (token) payload.token = token;
  if (!payload.label) return toast('اكتب اسم للحساب', true);
  try {
    if (id) {
      await api(`/api/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
      toast('التعديلات اتحفظت');
    } else {
      await api('/api/accounts', { method: 'POST', body: JSON.stringify(payload) });
      toast('الحساب اتضاف');
    }
    closeModals();
    await loadState();
  } catch (e) { toast(e.message, true); }
}

async function openProxyModal(id) {
  const a = state.accounts.find((x) => x.id === id);
  if (!a) return;
  $('px-id').value = id;
  $('px-type').value = a.proxy.type || 'http';
  $('px-note').value = a.proxy.note || '';
  $('px-line').value = '…جاري التحميل';
  openModal('modal-proxy');
  try {
    const r = await api(`/api/accounts/${id}/proxy`);
    $('px-line').value = r.line || '';
  } catch (e) {
    $('px-line').value = '';
    toast(e.message, true);
  }
}

async function saveProxy() {
  const id = $('px-id').value;
  const payload = {
    proxy_type: $('px-type').value,
    proxy_line: $('px-line').value.trim(),
    proxy_note: $('px-note').value.trim(),
  };
  try {
    await api(`/api/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
    toast('البروكسي اتحفظ');
    await loadState();
  } catch (e) { toast(e.message, true); }
}

async function cancelPlan(id) {
  if (!confirm('تلغي خطة التطوير للحساب ده؟')) return;
  try {
    await api(`/api/accounts/${id}/plan/cancel`, { method: 'POST' });
    toast('الخطة اتلغت');
    await loadState();
  } catch (e) { toast(e.message, true); }
}

async function testProxy() {
  const id = $('px-id').value;
  const btn = $('px-test');
  btn.disabled = true;
  btn.textContent = 'بنجرّب…';
  try {
    const r = await api(`/api/accounts/${id}/proxy/test`, { method: 'POST' });
    toast(`البروكسي شغّال — الـ IP: ${r.ip}`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = 'اختبار الاتصال';
    loadState();
  }
}

function openPlanModal() {
  if (!state.selected.size) return toast('اختار حسابات الأول', true);
  state.planSteps = [];
  $('plan-currency').innerHTML = Object.entries(window.CURRENCIES)
    .map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');
  $('plan-perk').innerHTML = Object.entries(window.PERKS)
    .map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join('');
  $('plan-count').value = '';
  renderPlanSteps();
  openModal('modal-plan');
}

function addPlanStep() {
  const perk = $('plan-perk').value;
  const count = parseInt($('plan-count').value, 10);
  if (!count || count <= 0) return toast('اكتب عدد أكبر من صفر', true);
  if (count > 300) return toast('أقصى عدد للخطوة الواحدة 300', true);
  const label = window.PERKS[perk]?.label || perk;
  state.planSteps.push({ perk, count, label });
  $('plan-count').value = '';
  renderPlanSteps();
}

function removePlanStep(idx) {
  state.planSteps.splice(idx, 1);
  renderPlanSteps();
}

function movePlanStep(idx, dir) {
  const target = idx + dir;
  if (target < 0 || target >= state.planSteps.length) return;
  [state.planSteps[idx], state.planSteps[target]] = [state.planSteps[target], state.planSteps[idx]];
  renderPlanSteps();
}

function renderPlanSteps() {
  const list = state.planSteps;
  if (!list.length) {
    $('plan-steps').innerHTML = '<div class="province" style="color:var(--muted)">لسه مفيش خطوات — ضيف واحدة فوق</div>';
    return;
  }
  $('plan-steps').innerHTML = list.map((s, i) => `
    <div class="province" style="display:flex;align-items:center;gap:8px">
      <span style="color:var(--sand);font-family:var(--font-mono);font-size:12px;flex-shrink:0">${i + 1}</span>
      <span style="flex:1">${s.count} × ${esc(s.label)}</span>
      <button class="btn btn-sm btn-ghost" onclick="movePlanStep(${i}, -1)" ${i === 0 ? 'disabled' : ''}>↑</button>
      <button class="btn btn-sm btn-ghost" onclick="movePlanStep(${i}, 1)" ${i === list.length - 1 ? 'disabled' : ''}>↓</button>
      <button class="btn btn-sm btn-danger" onclick="removePlanStep(${i})">حذف</button>
    </div>`).join('');
}

async function startPlan() {
  if (!state.planSteps.length) return toast('ضيف خطوة واحدة على الأقل', true);
  const ids = [...state.selected];
  try {
    const r = await api('/api/command', {
      method: 'POST',
      body: JSON.stringify({
        kind: 'upgrade_plan', account_ids: ids,
        payload: {
          steps: state.planSteps.map((s) => ({ perk: s.perk, count: s.count })),
          currency: $('plan-currency').value,
          spread: $('plan-spread').checked,
        },
      }),
    });
    toast(r.note);
    closeModals();
    setTimeout(loadState, 1500);
  } catch (e) { toast(e.message, true); }
}

async function openTravelModal() {
  state.expandedCountry = null;
  $('tr-search').value = '';
  openModal('modal-travel');
  if (state.countries.length) return renderCountries();

  $('tr-hint').textContent = 'بنجيب قايمة الدول من اللعبة…';
  try {
    const r = await api('/api/countries');
    state.countries = r.countries;
    $('tr-hint').textContent = `${r.countries.length} دولة متاحة`;
    renderCountries();
  } catch (e) {
    $('tr-hint').textContent = e.message;
    $('tr-list').innerHTML =
      '<div class="province" style="color:var(--muted)">مقدرناش نجيب القايمة — اكتب اسم المنطقة بنفسك واعمل سفر مباشر.</div>' +
      '<div style="padding:10px;display:flex;gap:6px">' +
      '<input class="field" id="tr-manual" placeholder="اسم المنطقة بالظبط زي ما هي في اللعبة" style="flex:1">' +
      '<button class="btn btn-go btn-sm" onclick="manualTravel()">سفر</button></div>';
  }
}

function manualTravel() {
  const name = ($('tr-manual')?.value || '').trim();
  if (!name) return;
  runGroup('travel', { destination: name }, $('tr-spread').checked);
  closeModals();
}

function renderCountries() {
  const term = ($('tr-search').value || '').trim().toLowerCase();
  const list = state.countries.filter((c) => {
    if (!term) return true;
    if (c.country_name.toLowerCase().includes(term)) return true;
    return c.provinces.some((p) => p.name.toLowerCase().includes(term));
  });

  if (!list.length) {
    $('tr-list').innerHTML = '<div class="province" style="color:var(--muted)">مفيش نتيجة</div>';
    return;
  }

  $('tr-list').innerHTML = list.map((c) => {
    const open = state.expandedCountry === c.country_name;
    const matchesCountryName = term && c.country_name.toLowerCase().includes(term);
    // لو البحث طابق اسم الدولة نفسها، نعرض كل مناطقها — مش بس اللي فيها نفس الحروف
    const provinces = (term && !matchesCountryName)
      ? c.provinces.filter((p) => p.name.toLowerCase().includes(term))
      : c.provinces;
    const shouldShow = open || matchesCountryName || (term && provinces.length > 0 && !matchesCountryName);

    const rows = shouldShow ? provinces.map((p) => `
      <div class="province" style="padding-inline-start:26px;display:flex;align-items:center;gap:8px">
        <span style="flex:1">${p.icon ? p.icon + ' ' : ''}${p.is_capital ? '⭐ ' : ''}${esc(p.name)}</span>
        <button class="btn btn-sm btn-go" onclick="event.stopPropagation();travelTo('${esc(p.name).replace(/'/g, "\\'")}')">سفر</button>
      </div>`).join('') : '';

    const flag = c.flag_url
      ? `<img src="${esc(c.flag_url)}" alt="" style="width:20px;height:14px;object-fit:cover;border-radius:2px;flex-shrink:0">`
      : '';

    return `
      <div class="province" style="display:flex;align-items:center;gap:8px;font-weight:600"
           onclick="toggleCountry('${esc(c.country_name).replace(/'/g, "\\'")}')">
        ${flag}
        <span style="flex:1">${esc(c.country_name)} <span style="color:var(--muted);font-weight:400">(${c.provinces.length})</span></span>
        <button class="btn btn-sm" onclick="event.stopPropagation();applyVisa('${c.country_id || ''}','${esc(c.country_name).replace(/'/g, "\\'")}')">طلب فيزا</button>
        <button class="btn btn-sm" onclick="event.stopPropagation();applyResidence('${c.country_id || ''}','${esc(c.country_name).replace(/'/g, "\\'")}')">طلب إقامة</button>
      </div>
      ${rows}
    `;
  }).join('');
}

function toggleCountry(name) {
  state.expandedCountry = state.expandedCountry === name ? null : name;
  renderCountries();
}

function travelTo(name) {
  runGroup('travel', { destination: name }, $('tr-spread').checked);
  closeModals();
}

function applyVisa(countryId, countryName) {
  if (!countryId) return toast('الدولة دي من غير رقم تعريف — مش هينفع نطلب فيزا ليها', true);
  runGroup('visa', { country_id: countryId, country_name: countryName }, $('tr-spread').checked);
  closeModals();
}

function applyResidence(countryId, countryName) {
  if (!countryId) return toast('الدولة دي من غير رقم تعريف — مش هينفع نطلب إقامة ليها', true);
  runGroup('residence', { country_id: countryId, country_name: countryName }, $('tr-spread').checked);
  closeModals();
}

function renderLog() {
  if (!state.logs.length) {
    $('log').innerHTML = '<div class="log-row"><span class="msg" style="color:var(--muted)">لسه مفيش أحداث</span></div>';
    return;
  }
  $('log').innerHTML = state.logs.map((l) => {
    const t = new Date(l.ts);
    const hhmm = t.toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit', hour12: false });
    return `<div class="log-row ${esc(l.level)}">
      <time>${hhmm}</time><span class="msg">${esc(l.message)}</span>
    </div>`;
  }).join('');
}

function openModal(id) { $(id).classList.add('open'); }
function closeModals() {
  document.querySelectorAll('.overlay').forEach((o) => o.classList.remove('open'));
}

function bind() {
  $('btn-add').onclick = () => openAccountModal();
  $('acc-save').onclick = saveAccount;
  $('px-save').onclick = saveProxy;
  $('plan-go').onclick = startPlan;
  $('px-test').onclick = testProxy;
  $('tr-search').oninput = renderCountries;

  $('btn-travel').onclick = openTravelModal;
  $('btn-upgrade').onclick = () => runGroup('upgrade');
  $('btn-plan').onclick = openPlanModal;
  $('btn-autoupgrade').onclick = () => runGroup('auto_upgrade');
  $('btn-refresh').onclick = () => runGroup('refresh', {}, false);

  $('btn-select-all').onclick = () => {
    visibleAccounts().forEach((a) => state.selected.add(a.id));
    renderAccounts(); renderPickState();
  };
  $('btn-select-none').onclick = () => {
    state.selected.clear();
    renderAccounts(); renderPickState();
  };
  $('squad-filter').onchange = (e) => {
    state.squadFilter = e.target.value;
    renderAccounts();
  };
  $('btn-tick').onclick = async () => {
    try {
      const r = await api('/api/tick', { method: 'POST' });
      toast(r.skipped ? r.reason : `نفّذ ${r.executed} مهمة`);
      setTimeout(loadState, 1000);
    } catch (e) { toast(e.message, true); }
  };

  document.querySelectorAll('[data-close]').forEach((b) => { b.onclick = closeModals; });
  document.querySelectorAll('.overlay').forEach((o) => {
    o.addEventListener('click', (e) => { if (e.target === o) closeModals(); });
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModals(); });
}

bind();
loadState();
setInterval(loadState, 8000);
"""


# ==============================================================================
#  [٦] صفحات HTML
# ==============================================================================

FONTS = ("https://fonts.googleapis.com/css2?family=Reem+Kufi:wght@400;600"
         "&family=Tajawal:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap")

LOGIN_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ app_name }} — تسجيل الدخول</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{{ fonts }}" rel="stylesheet">
<link rel="stylesheet" href="/assets/app.css">
</head>
<body>
<div class="login-page">
  <form class="login-box" method="post" autocomplete="off">
    <svg class="brand-mark" viewBox="0 0 100 100" aria-hidden="true">
      <polygon points="50,5 76.4,86.4 7.2,36.1 92.8,36.1 23.6,86.4"/>
    </svg>
    <h1>{{ app_name }}</h1>
    {% if error %}<div class="login-err">{{ error }}</div>{% endif %}
    <div class="form-row">
      <label for="username">اسم المستخدم</label>
      <input class="field" id="username" name="username" required autofocus>
    </div>
    <div class="form-row">
      <label for="password">كلمة السر</label>
      <input class="field" id="password" name="password" type="password" required>
    </div>
    <button class="btn btn-primary" type="submit">دخول</button>
  </form>
</div>
</body>
</html>"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ app_name }}</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{{ fonts }}" rel="stylesheet">
<link rel="stylesheet" href="/assets/app.css">
</head>
<body>
<div class="wrap">

  <header class="topbar">
    <div class="brand">
      <svg class="brand-mark" viewBox="0 0 100 100" aria-hidden="true">
        <polygon points="50,5 76.4,86.4 7.2,36.1 92.8,36.1 23.6,86.4"/>
      </svg>
      <div>
        <h1 class="brand-name">{{ app_name }}</h1>
        <p class="brand-sub">إدارة الحسابات والتحرّك الجماعي</p>
      </div>
    </div>
    <div class="topbar-spacer"></div>
    <div class="chips" id="chips"></div>
    <a class="btn btn-ghost btn-sm" href="/logout">خروج</a>
  </header>

  <div class="command-bar">
    <div class="command-row">
      <select class="field" id="squad-filter" style="max-width:170px">
        <option value="">كل المجموعات</option>
      </select>
      <button class="btn btn-sm" id="btn-select-all">اختيار الكل</button>
      <button class="btn btn-sm" id="btn-select-none">إلغاء الاختيار</button>
      <span class="command-count" id="pick-count">مفيش اختيار</span>
      <div class="topbar-spacer"></div>
      <button class="btn btn-go btn-sm" id="btn-travel" disabled>الدول والسفر</button>
      <button class="btn btn-sm" id="btn-upgrade" disabled>ترقية</button>
      <button class="btn btn-sm" id="btn-plan" disabled>خطة تطوير</button>
      <button class="btn btn-sm" id="btn-autoupgrade" disabled>تطوير تلقائي</button>
      <button class="btn btn-sm" id="btn-refresh" disabled>تحديث البيانات</button>
      <button class="btn btn-primary btn-sm" id="btn-add">+ حساب</button>
    </div>
  </div>

  <div class="section-head">
    <h2>الحسابات</h2>
    <div class="rule"></div>
    <button class="btn btn-ghost btn-sm" id="btn-tick">تشغيل نبضة الآن</button>
  </div>

  <div id="accounts"></div>

  <div class="section-head">
    <h2>السجل</h2>
    <div class="rule"></div>
  </div>
  <div class="log" id="log"></div>

</div>

<div class="overlay" id="modal-account">
  <div class="modal">
    <div class="modal-head"><h3 id="account-modal-title">حساب جديد</h3></div>
    <div class="modal-body">
      <input type="hidden" id="acc-id">
      <div class="form-row">
        <label for="acc-label">اسم الحساب عندك</label>
        <input class="field" id="acc-label" placeholder="مثلاً: الحساب الأساسي">
      </div>
      <div class="form-row">
        <label for="acc-squad">المجموعة</label>
        <input class="field" id="acc-squad" list="squad-options" placeholder="المجموعة الأولى">
        <datalist id="squad-options"></datalist>
        <div class="hint">الحسابات اللي في نفس المجموعة بتتحرّك مع بعض بأمر واحد.</div>
      </div>
      <div class="form-row">
        <label for="acc-token">التوكن</label>
        <input class="field" id="acc-token" placeholder="سيبه فاضي لو مش عايز تغيّره">
        <div class="hint">بيتخزّن في قاعدة البيانات ومبيظهرش تاني في الواجهة.</div>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn btn-primary" id="acc-save">حفظ</button>
      <button class="btn btn-ghost" data-close>إلغاء</button>
    </div>
  </div>
</div>

<div class="overlay" id="modal-proxy">
  <div class="modal">
    <div class="modal-head"><h3>بروكسي الحساب</h3></div>
    <div class="modal-body">
      <input type="hidden" id="px-id">
      <div class="form-row">
        <label for="px-type">النوع</label>
        <select class="field" id="px-type" style="width:100%">
          <option value="http">HTTP</option>
          <option value="https">HTTPS</option>
          <option value="socks5">SOCKS5</option>
          <option value="socks5h">SOCKS5H</option>
        </select>
      </div>
      <div class="form-row">
        <label for="px-line">بيانات البروكسي</label>
        <input class="field" id="px-line" dir="ltr"
               placeholder="عنوان:منفذ:يوزر:باسورد">
        <div class="hint">
          الصق السطر زي ما هو، مثال: <code dir="ltr">108.165.3.251:5382:ozyytuow:0tdkwosbhga2</code><br>
          لو مفيش يوزر وباسورد، اكتب العنوان والمنفذ بس.
        </div>
      </div>
      <div class="form-row">
        <label for="px-note">ملاحظة</label>
        <input class="field" id="px-note" placeholder="مثلاً: المغرب — الدار البيضاء">
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn btn-primary" id="px-save">حفظ</button>
      <button class="btn btn-go" id="px-test">اختبار الاتصال</button>
      <button class="btn btn-ghost" data-close>إغلاق</button>
    </div>
  </div>
</div>

<div class="overlay" id="modal-plan">
  <div class="modal">
    <div class="modal-head"><h3>خطة تطوير بالتتابع</h3></div>
    <div class="modal-body">
      <div class="form-row">
        <label for="plan-currency">العملة</label>
        <select class="field" id="plan-currency" style="width:100%"></select>
      </div>

      <div class="form-row">
        <label>أضف خطوة (مهارة + عدد مرات)</label>
        <div style="display:flex;gap:6px">
          <select class="field" id="plan-perk" style="flex:1"></select>
          <input class="field" id="plan-count" type="number" min="1" max="300"
                 placeholder="العدد" style="width:88px">
          <button class="btn btn-sm btn-primary" onclick="addPlanStep()">إضافة</button>
        </div>
        <div class="hint">
          مثال: أضف "٥٠ × العالِم" ثم أضف "٥٠ × الثكنات" — هينفّذوا بالترتيب ده بالظبط.<br>
          ملحوظة: اللعبة بتسمح بترقية واحدة بس في نفس الوقت، فكل ترقية بتستنى
          الوقت الحقيقي اللي اللعبة بتحدده (مش وقت ثابت) — ممكن ٥٠ ترقية تاخد
          أيام حسب مستوى الحساب، ودي حاجة من اللعبة نفسها مش من البوت.
        </div>
      </div>

      <div class="province-list" id="plan-steps" style="max-height:200px;margin-top:8px"></div>

      <div class="form-row" style="margin-top:14px">
        <label class="toggle" style="width:100%">
          <input type="checkbox" id="plan-spread" checked>
          <span>وزّع الحسابات على وقت لو مختار أكتر من حساب</span>
        </label>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn btn-primary" id="plan-go">ابدأ الخطة</button>
      <button class="btn btn-ghost" data-close>إلغاء</button>
    </div>
  </div>
</div>

<div class="overlay" id="modal-travel">
  <div class="modal">
    <div class="modal-head"><h3>الدول والمناطق</h3></div>
    <div class="modal-body">
      <div class="form-row">
        <label for="tr-search">دوّر على دولة أو منطقة</label>
        <input class="field" id="tr-search" placeholder="اكتب اسم الدولة أو المنطقة…">
        <div class="hint" id="tr-hint">بنجيب قايمة الدول من اللعبة…</div>
      </div>
      <div class="province-list" id="tr-list" style="max-height:340px"></div>
      <div class="form-row" style="margin-top:14px">
        <label class="toggle" style="width:100%">
          <input type="checkbox" id="tr-spread" checked>
          <span>وزّع الأوامر على وقت بدل ما الكل يتحرّك في نفس اللحظة</span>
        </label>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn btn-ghost" data-close>إغلاق</button>
    </div>
  </div>
</div>

<div class="toast-stack" id="toasts"></div>

<script>
  window.PERKS = {{ perks | tojson }};
  window.CURRENCIES = {{ currencies | tojson }};
</script>
<script src="/assets/app.js"></script>
</body>
</html>"""


# ==============================================================================
#  [٧] المسارات
# ==============================================================================

# static_folder=None عشان نقدّم الـ CSS و JS بنفسنا من نفس الملف
app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
)
# من غير السطرين دول المفاتيح بتتّرتب أبجدياً، فترتيب القوايم في الواجهة بيتقلب
app.json.sort_keys = False
app.jinja_env.policies["json.dumps_kwargs"] = {"sort_keys": False}


def same_secret(given, expected):
    """
    مقارنة ثابتة الوقت. بنحوّل لـ bytes الأول لأن hmac.compare_digest
    بيرمي TypeError لو النص فيه حروف مش إنجليزي (زي كلمة سر بالعربي).
    """
    return hmac.compare_digest(
        str(given or "").encode("utf-8"),
        str(expected or "").encode("utf-8"),
    )


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("owner"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "لازم تسجّل دخول"}), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


# ── الملفات الثابتة ──────────────────────────────────────
@app.route("/assets/app.css")
def asset_css():
    return Response(CSS, mimetype="text/css",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.route("/assets/app.js")
def asset_js():
    return Response(JS, mimetype="application/javascript",
                    headers={"Cache-Control": "public, max-age=3600"})


# ── الدخول ───────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template_string(LOGIN_HTML, app_name=APP_NAME, fonts=FONTS)

    if not OWNER_PASS:
        return render_template_string(
            LOGIN_HTML, app_name=APP_NAME, fonts=FONTS,
            error="مفيش كلمة سر متسجّلة على السيرفر. ضيف OWNER_PASS في إعدادات Render."), 500

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if not (same_secret(username, OWNER_USER) and same_secret(password, OWNER_PASS)):
        time.sleep(1)
        return render_template_string(
            LOGIN_HTML, app_name=APP_NAME, fonts=FONTS,
            error="اسم المستخدم أو كلمة السر غلط."), 401

    session.permanent = True
    session["owner"] = username
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    return render_template_string(INDEX_HTML, app_name=APP_NAME, fonts=FONTS,
                                  perks=PERKS, currencies=CURRENCIES)


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "mikael-bot"})


# ── الحالة ───────────────────────────────────────────────
def _plan_summary(plan):
    """بيحوّل بيانات الخطة الخام لملخّص واضح للواجهة، أو None لو مفيش خطة."""
    if not plan or not isinstance(plan, dict):
        return None
    steps = plan.get("steps") or []
    idx = plan.get("step_index", 0)
    if idx >= len(steps):
        return None
    step = steps[idx]
    total_remaining = sum(s["count"] for s in steps[idx + 1:]) + \
        (step["count"] - plan.get("done_in_step", 0))
    return {
        "current_perk": step["perk"],
        "current_label": PERKS.get(step["perk"], {}).get("label", step["perk"]),
        "done_in_step": plan.get("done_in_step", 0),
        "step_count": step["count"],
        "step_index": idx + 1,
        "total_steps": len(steps),
        "total_remaining": total_remaining,
    }


def _public_account(row):
    """بنشيل التوكن وكلمة سر البروكسي قبل ما نبعت البيانات للواجهة."""
    return {
        "id": row["id"], "label": row["label"], "squad": row["squad"],
        "enabled": row["enabled"], "has_token": bool(row["token"]),
        "perk": row["perk"], "currency": row["currency"],
        "auto_upgrade": row["auto_upgrade"], "auto_quests": row["auto_quests"],
        "auto_wheel": row["auto_wheel"], "auto_work": row["auto_work"],
        "auto_pills": row["auto_pills"], "pills_limit": row["pills_limit"],
        "auto_military": row["auto_military"],
        "military_joined_until": row["military_joined_until"].isoformat()
                                  if row["military_joined_until"] else None,
        "upgrade_plan": _plan_summary(row["upgrade_plan"]),
        "proxy": {
            "type": row["proxy_type"], "note": row["proxy_note"],
            "line_masked": (f"{row['proxy_host']}:{row['proxy_port']}"
                           f"{':' + row['proxy_user'] + ':••••••' if row['proxy_user'] else ''}")
                           if row["proxy_host"] else "",
            "configured": bool(row["proxy_host"] and row["proxy_port"]),
        },
        "game_name": row["game_name"], "avatar_url": row["avatar_url"],
        "level_num": row["level_num"],
        "xp_pct": row["xp_pct"], "balance": row["balance"],
        "diamonds": row["diamonds"], "location": row["location"],
        "nation": row["nation"],
        "travel": {
            "destination": row["travel_destination"],
            "sent_at": row["travel_sent_at"].isoformat() if row["travel_sent_at"] else None,
        } if row["travel_destination"] else None,
        "skills": {
            "barracks": row["lv_barracks"], "war_techniques": row["lv_war"],
            "scientist": row["lv_scientist"], "supply_drill": row["lv_supply"],
        },
        "status": row["status"], "last_error": row["last_error"],
        "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
        "upgrade_until": row["upgrade_until"].isoformat() if row["upgrade_until"] else None,
        "work_until": row["work_until"].isoformat() if row["work_until"] else None,
    }


@app.route("/api/state")
@login_required
def api_state():
    accounts = [_public_account(r) for r in list_accounts()]
    logs = db_all("SELECT id, account_id, level, message, ts FROM logs ORDER BY id DESC LIMIT 60")
    pending = db_one("SELECT COUNT(*) AS c FROM tasks WHERE status='pending'")
    return jsonify({
        "ok": True,
        "accounts": accounts,
        "squads": sorted({a["squad"] for a in accounts if a["squad"]}),
        "logs": [{"id": l["id"], "account_id": l["account_id"], "level": l["level"],
                  "message": l["message"], "ts": l["ts"].isoformat()} for l in logs],
        "summary": {
            "total": len(accounts),
            "running": sum(1 for a in accounts if a["enabled"]),
            "errors": sum(1 for a in accounts if a["status"] == "error"),
            "pending_tasks": pending["c"] if pending else 0,
        },
    })


# ── إدارة الحسابات ───────────────────────────────────────
_EDITABLE_TEXT = {"label", "token", "squad", "perk", "currency", "proxy_type", "proxy_note"}
_EDITABLE_BOOL = {"enabled", "auto_upgrade", "auto_quests", "auto_wheel", "auto_work",
                  "auto_pills", "auto_military"}


@app.route("/api/accounts", methods=["POST"])
@login_required
def api_create_account():
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    if not label:
        return jsonify({"ok": False, "error": "اكتب اسم للحساب"}), 400
    token = (data.get("token") or "").strip()

    row = db_execute(
        "INSERT INTO accounts (label, token, squad, sort_order) "
        "VALUES (%s,%s,%s,(SELECT COALESCE(MAX(sort_order),0)+1 FROM accounts)) RETURNING id",
        (label, token, (data.get("squad") or "المجموعة الأولى").strip()), returning=True)
    add_log(f"اتضاف حساب جديد: {label}", "ok", row["id"])
    if token:
        queue_task(row["id"], "refresh")
    return jsonify({"ok": True, "id": row["id"]})


@app.route("/api/accounts/<int:account_id>", methods=["PATCH"])
@login_required
def api_update_account(account_id):
    account = get_account(account_id)
    if not account:
        return jsonify({"ok": False, "error": "الحساب مش موجود"}), 404

    data = request.get_json(silent=True) or {}
    sets, params = [], []

    for field in _EDITABLE_TEXT:
        if field in data:
            value = (data.get(field) or "").strip()
            if field == "perk" and value not in PERKS:
                return jsonify({"ok": False, "error": "مهارة غير معروفة"}), 400
            if field == "currency" and value not in CURRENCIES:
                return jsonify({"ok": False, "error": "عملة غير معروفة"}), 400
            sets.append(f"{field}=%s")
            params.append(value)

    for field in _EDITABLE_BOOL:
        if field in data:
            sets.append(f"{field}=%s")
            params.append(bool(data.get(field)))

    # البروكسي بيتبعت كسطر واحد "عنوان:منفذ:يوزر:باسورد" ونفكّه هنا
    if "proxy_line" in data:
        raw = (data.get("proxy_line") or "").strip()
        if not raw:
            sets += ["proxy_host=%s", "proxy_port=%s", "proxy_user=%s", "proxy_pass=%s"]
            params += ["", "", "", ""]
        else:
            try:
                parsed = parse_proxy_line(raw)
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            sets += ["proxy_host=%s", "proxy_port=%s", "proxy_user=%s", "proxy_pass=%s"]
            params += [parsed["proxy_host"], parsed["proxy_port"],
                      parsed["proxy_user"], parsed["proxy_pass"]]

    if "pills_limit" in data:
        try:
            limit = int(data.get("pills_limit"))
            if limit < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "حد الماس لازم يكون رقم صحيح موجب"}), 400
        sets.append("pills_limit=%s")
        params.append(limit)

    if not sets:
        return jsonify({"ok": False, "error": "مفيش حاجة تتغيّر"}), 400

    params.append(account_id)
    db_execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id=%s", params)

    if data.get("token"):
        db_execute("UPDATE accounts SET status='idle', last_error='' WHERE id=%s", (account_id,))
        queue_task(account_id, "refresh")

    if data.get("auto_upgrade") and not account["auto_upgrade"]:
        queue_task(account_id, "auto_upgrade")

    return jsonify({"ok": True})


@app.route("/api/accounts/<int:account_id>", methods=["DELETE"])
@login_required
def api_delete_account(account_id):
    account = get_account(account_id)
    if not account:
        return jsonify({"ok": False, "error": "الحساب مش موجود"}), 404
    db_execute("DELETE FROM accounts WHERE id=%s", (account_id,))
    add_log(f"اتمسح حساب: {account_title(account)}", "warn")
    return jsonify({"ok": True})


@app.route("/api/accounts/<int:account_id>/plan/cancel", methods=["POST"])
@login_required
def api_cancel_plan(account_id):
    account = get_account(account_id)
    if not account:
        return jsonify({"ok": False, "error": "الحساب مش موجود"}), 404
    db_execute("UPDATE accounts SET upgrade_plan=NULL WHERE id=%s", (account_id,))
    db_execute(
        "DELETE FROM tasks WHERE account_id=%s AND kind='plan_step' AND status='pending'",
        (account_id,))
    add_log("خطة التطوير اتلغت", "warn", account_id)
    return jsonify({"ok": True})


@app.route("/api/accounts/<int:account_id>/proxy")
@login_required
def api_get_proxy(account_id):
    """بترجع البروكسي كامل (من غير إخفاء) — تتستخدم بس وقت فتح نافذة التعديل."""
    account = get_account(account_id)
    if not account:
        return jsonify({"ok": False, "error": "الحساب مش موجود"}), 404
    line = ""
    if account["proxy_host"]:
        line = f"{account['proxy_host']}:{account['proxy_port']}"
        if account["proxy_user"]:
            line += f":{account['proxy_user']}:{account['proxy_pass']}"
    return jsonify({"ok": True, "line": line, "type": account["proxy_type"],
                    "note": account["proxy_note"]})


@app.route("/api/accounts/<int:account_id>/proxy/test", methods=["POST"])
@login_required
def api_test_proxy(account_id):
    account = get_account(account_id)
    if not account:
        return jsonify({"ok": False, "error": "الحساب مش موجود"}), 404

    proxies = build_proxies(account)
    if not proxies:
        return jsonify({"ok": False, "error": "مفيش بروكسي متسجّل للحساب ده"}), 400

    try:
        ip = GameClient(account["token"], proxies=proxies).check_ip()
    except Exception as e:
        message = f"البروكسي مش رادّ — {type(e).__name__}"
        add_log(message, "error", account_id)
        return jsonify({"ok": False, "error": message}), 400

    add_log(f"البروكسي شغّال — الـ IP: {ip}", "ok", account_id)
    return jsonify({"ok": True, "ip": ip})


# ── الأوامر ──────────────────────────────────────────────
def _resolve_targets(data):
    """بيحوّل طلب الواجهة لقائمة IDs — حسابات بعينها أو مجموعة كاملة."""
    ids = data.get("account_ids")
    if isinstance(ids, list) and ids:
        rows = db_all("SELECT id FROM accounts WHERE id = ANY(%s) AND token<>'' "
                      "ORDER BY sort_order", ([int(i) for i in ids],))
        return [r["id"] for r in rows]

    squad = (data.get("squad") or "").strip()
    if squad:
        rows = db_all("SELECT id FROM accounts WHERE squad=%s AND token<>'' ORDER BY sort_order",
                      (squad,))
        return [r["id"] for r in rows]
    return []


@app.route("/api/command", methods=["POST"])
@login_required
def api_command():
    """
    أمر واحد لحساب أو لمجموعة.
    مثال: {"kind":"travel","squad":"القافلة الأولى","payload":{"destination":"Casablanca"}}
    """
    data = request.get_json(silent=True) or {}
    kind = (data.get("kind") or "").strip()

    if kind == "upgrade_plan":
        return _handle_upgrade_plan(data)

    if kind not in HANDLERS:
        return jsonify({"ok": False, "error": "أمر غير معروف"}), 400

    targets = _resolve_targets(data)
    if not targets:
        return jsonify({"ok": False, "error": "مفيش حسابات مختارة (أو مفيش توكن ليها)"}), 400

    payload = data.get("payload") or {}
    spread = bool(data.get("spread", True)) and len(targets) > 1
    count, total_delay = queue_group(targets, kind, payload, spread=spread)

    label = KIND_LABELS.get(kind, kind)
    if spread:
        note = f"أمر {label} اتحط على {count} حساب — هيتنفّذ على مدى {total_delay // 60} دقيقة تقريباً"
    else:
        note = f"أمر {label} اتحط على {count} حساب"
    add_log(note, "info")

    threading.Thread(target=run_tick, args=("command",), daemon=True).start()
    return jsonify({"ok": True, "queued": count, "spread_seconds": total_delay, "note": note})


_provinces_cache = {"data": None, "at": 0}
_countries_cache = {"data": None, "at": 0}


def _handle_upgrade_plan(data):
    """
    خطة تطوير بالتتابع: كذا خطوة، كل خطوة (مهارة + عدد مرات)، بتتنفذ بالكامل
    قبل ما اللي بعدها تبدأ. مثال: [{"perk":"scientist","count":50},
    {"perk":"barracks","count":50}] = ٥٠ ترقية علم، وبعدين ٥٠ ترقية ثكنات.
    """
    targets = _resolve_targets(data)
    if not targets:
        return jsonify({"ok": False, "error": "مفيش حسابات مختارة (أو مفيش توكن ليها)"}), 400

    payload = data.get("payload") or {}
    currency = (payload.get("currency") or "money").strip()
    if currency not in CURRENCIES:
        return jsonify({"ok": False, "error": "عملة غير معروفة"}), 400

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return jsonify({"ok": False, "error": "لازم تضيف خطوة واحدة على الأقل"}), 400

    steps = []
    for item in raw_steps:
        if not isinstance(item, dict):
            return jsonify({"ok": False, "error": "شكل الخطوة غلط"}), 400
        perk = (item.get("perk") or "").strip()
        if perk not in PERKS:
            return jsonify({"ok": False, "error": f"مهارة غير معروفة: {perk}"}), 400
        try:
            count = int(item.get("count"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "العدد لازم يكون رقم"}), 400
        if count <= 0 or count > MAX_PLAN_STEP_COUNT:
            return jsonify({
                "ok": False,
                "error": f"العدد في كل خطوة لازم يكون بين ١ و {MAX_PLAN_STEP_COUNT}",
            }), 400
        steps.append({"perk": perk, "count": count})

    total_per_account = sum(s["count"] for s in steps)
    if total_per_account > MAX_PLAN_TOTAL_COUNT:
        return jsonify({
            "ok": False,
            "error": f"إجمالي الخطة لكل حساب كبير قوي — أقصى حد {MAX_PLAN_TOTAL_COUNT} ترقية",
        }), 400

    spread = bool(payload.get("spread", True)) and len(targets) > 1
    delay = 0
    for account_id in targets:
        plan = {"steps": steps, "currency": currency, "step_index": 0, "done_in_step": 0}
        db_execute("UPDATE accounts SET upgrade_plan=%s::jsonb WHERE id=%s",
                  (json.dumps(plan), account_id))
        queue_task(account_id, "plan_step", delay_seconds=delay)
        if spread:
            delay += random.randint(GROUP_SPREAD_MIN, GROUP_SPREAD_MAX)

    steps_desc = " ← ".join(f"{s['count']}×{PERKS[s['perk']]['label']}" for s in steps)
    note = (f"خطة تطوير بدأت على {len(targets)} حساب: {steps_desc}. "
           f"هتمشي في الخلفية حسب وقت الترقية الحقيقي في اللعبة — مش وقت ثابت.")
    add_log(note, "info")

    threading.Thread(target=run_tick, args=("command",), daemon=True).start()
    return jsonify({"ok": True, "queued": len(targets), "note": note})


def _fetch_provinces_raw():
    cached = _provinces_cache.get("data")
    if cached and time.time() - _provinces_cache["at"] < 3600:
        return cached, True
    account = db_one("SELECT * FROM accounts WHERE token<>'' ORDER BY sort_order LIMIT 1")
    if not account:
        raise GameError("محتاج حساب واحد على الأقل بتوكن")
    raw = client_for(account).provinces()
    _provinces_cache["data"] = raw
    _provinces_cache["at"] = time.time()
    return raw, False


@app.route("/api/provinces")
@login_required
def api_provinces():
    """قايمة مناطق اللعبة المسطّحة — بنجيبها بأول حساب فيه توكن وبنكاشها في الذاكرة."""
    try:
        raw, cached = _fetch_provinces_raw()
    except GameError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"مقدرناش نجيب المناطق — {e}"}), 502

    provinces = []
    for p in raw:
        if isinstance(p, str):
            provinces.append({"id": p, "name": p})
        elif isinstance(p, dict):
            name = p.get("name") or p.get("title") or p.get("id")
            if name:
                provinces.append({"id": p.get("id", name), "name": name})
    return jsonify({"ok": True, "provinces": provinces, "cached": cached})


@app.route("/api/countries")
@login_required
def api_countries():
    """
    قايمة الدول وتحتها مناطقها — مبنية من بيانات المناطق نفسها (كل منطقة معاها
    country_id و country_name)، فمحتاجناش نداء تاني منفصل للدول.
    """
    try:
        raw, cached = _fetch_provinces_raw()
    except GameError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"مقدرناش نجيب الدول — {e}"}), 502

    by_country = {}
    for p in raw:
        if not isinstance(p, dict):
            continue
        cid = p.get("country_id")
        cname = p.get("country_name") or "بدون دولة"
        pname = p.get("name")
        if not pname:
            continue
        key = cid or cname
        if key not in by_country:
            by_country[key] = {
                "country_id": cid, "country_name": cname,
                "flag_url": p.get("country_flag", ""), "provinces": [],
            }
        by_country[key]["provinces"].append({
            "name": pname, "region": p.get("region", ""),
            "is_capital": bool(p.get("is_capital")),
            "icon": p.get("icon") or "",
        })

    countries = sorted(by_country.values(), key=lambda c: c["country_name"])
    for c in countries:
        c["provinces"].sort(key=lambda p: (not p["is_capital"], p["name"]))

    return jsonify({"ok": True, "countries": countries, "cached": cached})


@app.route("/api/tick", methods=["POST"])
@login_required
def api_manual_tick():
    return jsonify(run_tick("manual"))


@app.route("/cron/tick", methods=["GET", "POST"])
def cron_tick():
    """
    ده اللي بيصحّي السيرفر على Render المجاني وبينفّذ المهام.
    اربطه بـ cron-job.org كل ٥ دقايق:
        https://<اسم-الخدمة>.onrender.com/cron/tick?key=<CRON_SECRET>
    """
    if not CRON_SECRET:
        return jsonify({"ok": False, "error": "CRON_SECRET مش متسجّل"}), 503
    key = request.args.get("key") or request.headers.get("X-Cron-Key") or ""
    if not same_secret(key, CRON_SECRET):
        return jsonify({"ok": False, "error": "مفتاح غلط"}), 403
    return jsonify(run_tick("cron"))


# ==============================================================================
#  [٨] الإقلاع
# ==============================================================================

_started = False
_db_ready = False
_start_lock = threading.Lock()


def ensure_db():
    """
    بنعيد المحاولة عند كل طلب بدل ما البوت يفضل ميت لو القاعدة كانت نايمة
    لحظة الإقلاع — ده بيحصل مع Supabase المجاني بعد فترة خمول.
    """
    global _db_ready
    if _db_ready:
        return True
    try:
        init_db()
        _db_ready = True
    except Exception as e:
        log.error("القاعدة لسه مش جاهزة: %s", e)
    return _db_ready


@app.before_request
def _before(*_):
    if not _db_ready and request.endpoint not in ("asset_css", "asset_js", "healthz"):
        ensure_db()


def bootstrap():
    global _started
    with _start_lock:
        if _started:
            return
        _started = True

    ensure_db()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_tick, "interval", seconds=TICK_SECONDS, id="tick",
                      max_instances=1, coalesce=True)
    scheduler.start()
    log.info("النبضة الداخلية شغّالة كل %s ثانية", TICK_SECONDS)


bootstrap()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
