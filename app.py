"""
GNID BANK - Flask app (نسخة مجمّعة في ملف واحد)
==================================================
كل الصفحات (HTML) موجودة جوه الملف ده كـ strings بدل مجلد templates منفصل،
عشان يقل عدد الملفات في المشروع.

مميزات:
- تسجيل / تسجيل دخول (بيوزر تليجرام إلزامي)
- آي دي بنكي فريد لكل حساب (زي نظام البوت)
- تحويل بين المستخدمين بالآي دي
- سوق أسهم: طرح من الإدارة (IPO) + تداول بين المستخدمين (order book)
- 3 لغات: عربي / إنجليزي / برتغالي برازيلي

تشغيل محلي:
    pip install -r requirements.txt
    python app.py
"""

import os
import random
import secrets
import logging
import json
import re
import html
from datetime import datetime, timedelta

import requests
from apscheduler.schedulers.background import BackgroundScheduler

from flask import (
    Flask, request, redirect, url_for, render_template_string,
    flash, session, Response
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)  # ملاحظة: مفيش مجلد static - كل الـ CSS جوه الملف ده
_env_secret = os.environ.get("SECRET_KEY")
if _env_secret:
    app.config["SECRET_KEY"] = _env_secret
else:
    # ما فيش SECRET_KEY متظبط في متغيرات البيئة - بدل ما نستخدم قيمة ثابتة معروفة ("change-me")
    # اللي أي حد يقدر يخمنها ويزوّر جلسات مستخدمين، بنولّد مفتاح عشوائي قوي وقت التشغيل.
    # العيب الوحيد: جلسات المستخدمين هتتلغي لو السيرفر اتعمله ريستارت - أأمن بكتير من مفتاح ثابت مكشوف.
    app.config["SECRET_KEY"] = secrets.token_hex(32)
    logging.warning("SECRET_KEY مش متظبط في متغيرات البيئة - بيتستخدم مفتاح عشوائي مؤقت. اتظبطه في Environment Variables عشان جلسات المستخدمين متتلغيش مع كل ريستارت.")

# --- حماية إضافية على كوكي الجلسة: يفضل يشتغل بس مع HTTPS، ومش قابل للقراءة من JS، ومش بيتبعت مع طلبات cross-site ---
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FORCE_HTTPS_COOKIES", "1") != "0"
# قبل كده login_user() كان بيتنادى من غير remember=True، فـ Flask-Login كان بيعتبرها جلسة
# مؤقتة (session cookie) بتتمسح لوحدها من المتصفح، وده كان سبب رئيسي في إن المستخدمين
# بيلاقوا نفسهم اتسجل خروجهم فجأة من غير أي سبب واضح. دلوقتي الجلسة بتفضل شهر كامل.
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# --- قاعدة البيانات: Postgres لو DATABASE_URL موجود، وإلا SQLite محلي ---
db_url = os.environ.get("DATABASE_URL")
if db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif db_url.startswith("postgresql://") and "+psycopg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
else:
    DATA_DIR = os.environ.get("DATA_DIR", ".")
    os.makedirs(DATA_DIR, exist_ok=True)
    db_url = f"sqlite:///{os.path.join(DATA_DIR, 'bank.db')}"

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# مهم مع Supabase pooler: يتأكد إن الاتصال لسه شغال قبل كل استعلام،
# ويجدد الاتصالات القديمة عشان نتجنب أخطاء "SSL error / connection closed"
# اللي بتحصل بسبب الاتصال المستمر لمراقبة الخزنة كل دقيقة.
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 240,
}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


@login_manager.unauthorized_handler
def _unauthorized():
    """بدل رسالة Flask-Login الإنجليزية الافتراضية، نبعت رسالة مترجمة حسب لغة المستخدم الحالية."""
    flash(tr("please_login_message"))
    return redirect(url_for("login", next=request.path))

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- رقم إصدار التطبيق - يترفع مع كل تحديث/ميزة جديدة ---
APP_VERSION = "1.35.7"

LOGO_DATA_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAIAAABMXPacAAAy/0lEQVR42u29aZBk13Ue+J1z73svl9q6u3pBN4AGutHYAWIhCUKiSHGTKEq0TJMiKVvWNrIntIw0UkyMRzOhH2P/0sjjcDg0M7aD9kTY0pCWTJOUKHERQRIkQYEgia2xEugV6H2pPTPfu/ecMz/ey6yszKysqm5YmojpjIzuqqx82z33nuU73zmXGhMzuPb623vxtSG4JoBrArj2uiaAawK49romgGsCuPa6JoBrArj2uiaAawK49vqbe3lb+zut/dVGfTjmZaM+HDzn2pPSqMPpDXo8W/82rv6cdBVXNAMIBBClTRhAKP8l475T2ZZvrnue/tsg6/2u3WsTqDp5938Qk1rvQwZARGY6fBtEZGbr/Tp4P72v2bh1T2S2OjVWb7h7ciJiAGZmpP0nHLi6EYioHGMClYf0vtb7shnKb/nqWBs95lZdY4uzw8auCyLATLuPaavXWn0QW7tcRs6g9X8dfeWNptNmrmXWd5pRNznmr+UPq3PMAJiDSyuJUbUmBsZq86NfHkqDBxCtntNWJ+aQClq7eN8ghUEjT0gbqRYap296a3fUaYhGyGDMyxGn5Tmpe0C1gMhQriYaEAmtM00MVv2NBrQQDb4JRODyCkYYknv/N6v1u951x39O5bGg1Ym38YSidWbF4DyzvvvkvtOOfKD1btiv0T/Vf9T3S3WVniLDhue1zdlmw6AOGqM8zK5yDRi2oow2o8+u4pYG3VAz2/B0vTm44Tc3c7ZhWW40MW3M5Ubrge7n3ftZ/ZU2rVXHrbxN3MZmbtgDYOY3UqTMABRXeTbqugTlkzJ1fZLShhNRZces9yUrxVh+x8zMFFr6LeVUe2MesF/Ib8RpfHO8JzdmdmzGF+x9vsEliLo+owEEY1DsTkIwCGaibBIB6fqRASidVC615Nq4xQEeIPLkGCBTOBMiUyPb9DNy371r9ydaz1Mf+YxjHpyI/P9HAkJTJeJyvM0MpEye4KKqSaGIANWc37Ej27u7tm9347rZyT270tltSSP1aeqZAHAU1+rIpYXO2blw5vziqbMrJ84snru4EgsDHADnvXcUzdQG19rfWiQ8XoWNi3FsXaO0yfXU/7U+VUvOcRSV0AFCkqQ37mnefdv0vbfO3H7TxHU767NT2qy5zPuEHDOEK23nPCVp5nzdJSmYlNI80OJiPHGq/dyR+e89e+rJp8+9ePxyHgUAJ56ZVHR8tNlvR65Av2/m+wTXGO/b2DrBzBVorSEb1q/oiciBoCHA4L0/dKD24L3b7rtz6uDe5uwk1100MRLzYDgQswN57513RMTMxMzOMTnHjrxzjtk5n3CW1WppU0EX5zvPvLzw5W8d+9Jjxw+/dBYQuFrmvFgQY6tMzYCjQSMfvBs2WtcaoXJ0qT/eHjHDRiko39xokvbfh75xAuhpfCNiQDXkAO3ZU7///pm33LfjwN7adCpkYrCEfEqcMSWeM+8TT8zsjBwTOZd4z86xcyAwe+ccvHfOE9jIE7OpqppnrdW8z7Ytt1uPPz33x5//wZ8/cnhxqQVsTxNE5GZX/lA9u7CefdlYAP3fWGs5KwH0kJnhmGCzlnZIAMQEQAshigdumXzb23a+6e5sxxQQ1aKwuXri66nL2CeElJB6lzrnPLzzrGAQEuedd8zsHYgce3ZMPmHnHHtiXy4zAxnMUJAgdfV608H5F19Z/qM/+8F/+Nzhsxfn4OreOxEdryc3BJ3INtDbpWvbd86tC2BYmGMEMPQJdWMwJmIJBuQHbp14+B2ztx5KGomisAScOk6dSz3XPKcOCShzPmPnGY6MHaXepd4ljpPEe++9T5z3zntmNpCAYUTGSl4NYGJ25hwIXjiainZIpVGrNRv1I6fiH/7x05/40+8urwSX1AFTs+4U0b8JAWxp3fVGfxNjPXyXRHBmymSIXq3YeV36Q+/cc8fdPvOFFkiZUnapo9QhIar7NE3YM6fGNUYtoXqW1tPEewaxxqyd61Jbl1pFOycQe8+1Ojebtempiammm56qNWsJM5nEImonwhRE7CyoQrqrIkt9s9F46sXl/+0TT/7pF54CeZ/5KJHNg8a4J7A+SKsPTN20E19aDU4mtmS+NymA3tf6I08DEwsh08KSerj/4W33vaXZnCgsaI1dLUlSdgnIMxKmzLmUXUJSSzBTzxpJGkJ6dt6Onlp86djKyVPt8xeKywvtpXan07FCGFBAiSxL/USWTE8ls7MTN12/465Du+6/bfsdt8zs3TuVOSs6S61WIRo9p8aJQU1NY5huZr4++cdfPPJ7v//oybOXXG0aUhioD8u0tVr3DRJAvxEeHzKMxLW3aKkIBkh776Hph969Z/feXIuYaJo6nznJvKXsM3aOzMFSoola0szSEBvHXisOv3Dh8AsLR08tL7W1a70dADgFO4LrxrpqplCFli6DAEJId++YuPv2He962/53ve2Guw7uqddb7XYrL3qjSFA4zqcmZ46fdb/7vz/yJ194ziUThjj2MWnAPRkelvWQj9ECGK9PNo+i9KUdVg8hYougtLjn4e13vnmCkg4LaomvOUoICVHqfM1zSubVNTwndZ67lHz/8NJ3njp39FgH5oECznnnATKUbqCBGKbd9AKZKRFTCbNWICWJqQaDBSCktcYP373nIx+898ffuf+G3UlnZSVvBzA7lziwhOValvrp2X/+77/7e3/wdSWfOhcjjHU8plViIrQWtRrvGhmNdUOvxstcKwBjY0YSJNS3u/veN7XvAEsePSNjlzDVPGfOJcR1toTRSGoT9cbpM51vfuv8955aXFwuAMdJwsRmaqo2hOINGHmikd5eiaxxjAIxIF6/Z+pDP3bXf/PRe++4xXWWWiFGB2/E0dhTnNy2/TN/9dqv/s+fu7Sovs5SEEjHAYXMlYa4AgFsPsO3GbM+eAZSZz7GfOZAcs97ttenibTT4CQhpMSpo5Rd5ryHNchPTyaLS/6xR+e+/Z2z7baHZ+dgwiA1k/50jV0FfOCcwLJYRGBl+8z0r3z4Tb/29x/cu6++dOmSQJF6r2qdYtuOmcdeav3Cb/3no6cWfZqJalfnjHjSkWO9GQE44nSLyPDGmO1aY+Ulhtk7s9vft4N9EAkZsTMioAyfPBEZamnqfPOJx1c+9anjL73cisbOE4PUBFACw7j3HBsmJzaaNQwl7yxJ/HLbHnvyyKf/6iWfTT5w175mEkNh5BQOyyudQ/ubP/bOW7/+raPnLi/5pA41cOxX/av3MIpjMPrDtX91cClss6j9Vr5gzpjIqcSdd9dvenvTqMVqCcBEjskRebADOUhzIpu/mH7uv5x8/LEzeZG5tNSl0kOaiQaD8CrhtRUZ9KXeyMgUECNm+DSbmy++9Ojh7z174Z679t+0v95ZKVhTl1prOe6dsXe+4/ZHvnny4uWOy6iERLvRe9+dAIQ1ebENBVAe4shnw9Oqz3LSZtTQcIbUiNi8aDF7b+26t9YClj27hMkRHLFn54kY5ogmGrWXnu187j+9duFsdOkkEZkV3WQRjQwSr0wA6w2HqrEj7xuvnrj0J58/PFHf8dAD15tdijFjTvKVzr5d/h0P3/OFrz4/3yo8N0wVZCNvgLYigEofgpMevaJ30vE2YOgyVd64/3NHTmKx7b5s11szsWVHlJBLmByTY0qImZCQz9zME1+bf/RLF6OkLmFVqfD9UU7XmPzUlQmg/2yi6hPfLtwXv3H4xOtL7/nheydqrui0kVLexs170/vfdPPnv/BSWwJxpb9HQv9bFsCwDbhiY8AGkBq5xNiiNm93ux6qB2t5ShJ2TOQZDMdgBhJPLPVH/+LcC08tcJISA4i9jMpVDfR6z2LddLkxSJncKjunnEVKziuy5Nnnzzz2+Ll3vv3g7u3WKkKS0vLy8u0HJvbumv3sV15hl7AZKykrrXOr3Q/LJcvDbktver2RAgAYpAwnguwGve7tU4VfcsbM7IkckSfvSQkhS8ny+qOfu3Dq1WWXJqol5MIjjNsbKIDV2yR2mURYSc3ou30DQcwljZNnFr741Rfe8uAtt9zQzJcinOssrzxw742X5/SJZ49yUjfo8LpfG/dQGeKNVFO9DytayhvgWgBGYGOI8fZw3bsmtF6YqCP2jj0RAwl7xyFJ0qRoPvbnFy6ckMTXxWQM1WV8rmJrRrg0eo6h0NCanq5LZO3zbrsuo1OLLs0uzbW/8Mirb33wwIEbJ/KVgok77bl3vPXAE98/c/z0Iqd+YxW09sORI8z9yfQyn37l4D4rI7HE9rytQZNRg7EmKLmOXVIYsec49e0vXL5wosVJElBsZtqOZFqoqqpugvZBZGCYJzjnY95iaf+Pv/5T//L3f9FkZXjIjBSkGkOSubOL+cd/4/PfeX5lcsrnIXYUNbf8+//k3dsmUxNibC1NxszDl+MhOgl337RFAbCzJEqYuTdNb6QYFASBGoBoKgZFRCCbeOaRc+ePtFzWMAu0uencu/WBfzexAgwwI2LvRDjmyw+9+cDn/+Q3f/+f/vieqRURWTdQgEYxl/jz8/kv/PZnnz3aadbhhBdb7btuTX/nl96iISdKNmOxxmdK3gB6eiU5ggWt7bPpe2uhUEaPXVumwM1gjcQf+97iqReiT7yKvhFWZ4NJZ1QQO3ZJ6OSTk8n/+k8++OVP/uN3PViX8yfzVgfQ8dNMJfg6nzzf+qX/4S/OLGUNL6SYv3z5l//uoYfv2hmL9sj7HXCXBx5qYDXz2LmzqURzdQ0jS8LON09IrWNW8YL6byLL0stH3dHvrDj2MpI+p7ohAaAHMW0SM3cu00Ikn/97H7jvG5/+jd/7tft45dTyxYLZGZf8lzHr2pw5KdTV/EsnF37rnz7W4glWsYISu/Df//xdnrXLAbORV+8f636gvl8kw1rJunnazTskSgyKNnlrwruidcwxk+PuBZTIMfuwmL38rQWoNw6mg9RRM7KKbdnDeWh4XI3WMs5H3ZsRgyhhI/bSad1y8/Qf/atf+ZM//Mjt17Xmz11UNXaFUXDEY0NUMrASCKQRSa3xlcdf/oN/99zETC2oLiwsP3xf/YM/ckBDwa6Uo62rG8ZOFB6pNIdJAOPtnAueJ+PM3XVVISNTXWX9m4tOiLOTTyx25gN5NQyAd9Tju5ZPQqUvYLpeJLXB9Dch4qKQlOJv/6Mff+Q//aOP/8T2pUuvtdsFO28GqKgAsqFVIyttMkyicDrxbz759Bf+erlZD0UBi+1f//u3TdYzMXNmZFt25ctB4PHZy43jPQLBicWJOzymgsUSpy+p0gSYgJPUL78WL/ygzT5ZBUmHvWNbq3BGwc7D+nSUxQZi8SNvufULf/SLf/C7b93h5pcvzpdnN1MzU1WVAI396H33VOvMWSLA5dr4vX/52LmFJMmsWEruOZD95LtutKIgYmwGmRj1IW+eO7VeahTRaFonb62phFVNV4HkJIlyOzv95LyZX2cK20Ddw6hvmJYLYiPHj5klFD/x3ru+/P98/OFDPHfqtU7swKUkTkXKt6mYRKtgj3VvaaBiwUSSRI68fvkP/+i1ycZEtCLPOz/30weaSS2abJ5dN+A682b8p+F4r1/jmobpgzVMKLRixaJU6mRq6pxdfiVfOSPkR08uIzMyg/aj5qWu772rfErpUho2mBAmN+yq1XB5fmmFnIOYaRTLIdFisBhEFCKq2r/Kug9YLfsBQ1iJQJWTxqe++Oz3X15uNpPlleJNN6XveGCXxZyZr4wWzpv150aenaBq3MTkQdaQk6bUrZDSskYK7FvZpZeXiOpGq9Pk6t3N9YiRZUDYyYu8E4hgUDMNMYhE0agmaiJS/bChwRxw4UuCy0qBf/EfX4SlYlFC8cF372awwTaD6AzP4y3EAcMXIBBEmns9bRcS4r6knRHM4BO/+FooLpBnJXM9M7rJyXKl98aAhVCEIsQYYyxizKMUqrF6m6hIuaA2A2z036qouqT2te+e/8snL040s+X5pbfd2dy/d1KD0CbmyvBT8/qPUcW3I50PggJMykSa7fcqIGJzlSY3MjZHRFpg/sU2wEICG22gyJiM2XhNGZcxjAlcOqfleySYNUQ1qHQ4hYDYsZiXasdiVFGNolEsBI2FiW7oV428iqNo8P/hz461Cw65zk4lb3/LHlgg71BSAbaGX24GQR9hpAikJuJnuL4rM1Hq1pmVCScgOub2ac0vRrjyT7b1a22+lGXNAWYGU5UoIWiMpqqlARAxEVURCSpyZYtNhZ1PvvvshcefWahNUC7x3Q/sZWa16MxI3Zbo7rw++jgW3yAul3B9X+YaVeRLslrAFgkg1z4REDzRxoGrjSo3GW2013xogDFTyaAqEREAahZFRCRKLH8QEYlBYiGxEK3swUincz13YxUZJIKTIPrpr75GSaOzUtyxP7thtmGFgnW4TnprK8DGuWKDQiCgvi8RzgdH2IjIhZa1zwQmtnFTnjbtCPZZSyKrEpqJdzUpCk/iXO8Ig2oMIcao5cjHIDGIdN8hxCimceM868g/kJoqOfeNZy6cPBsSs5lJuu/W7aWNrgp7rkIA1g33bcwoEBTRuQZnO8hMCc4q37FCFBJHxYUYFwHfq34daWB4lXNnfe+uC7qm8rlLdGRTp+aYVDohX/7Jd9/xr//Z360lZuXdw0hMoqioxqCxUAkiUURijDFGlajBykBsXX9sGKZejUxhRuySpaXiG98/n2SE2Lr31hlA2bZWiXY1JUoEUz9rrkGiPKDhldRblp/umFmPwrMOKmvr16ePygmXlEQyA8ewvHt26nd/+aF/+OGdR19nEKNb1KxWTn3BKMBHVGOMsk4uYfQNmWHozgH+yuPnPvzOPQktHbyhkTBHVeqiEuvF7QMqzl/p8BMByazTJCIfummCFtY5K0TOSlbP1XqWPdvPnjnkgSj+ww/e+9/9wr3Xz7QWL5xrtSfZrSpfU1NVVYGCMEgZVhXVMhAzbNXKr2K3Bl975tWlE6fbt11v+6+r7drePHV52bOXrfhUfgjJ2mx+T0hrO+qsUJXu7Ci58SCHMGdhSVASbTHsCFs3YT0G6igrH0s+lhDIE0elkLfuvGXX//SPH3r/2ybzpbm5xVDLWDsisXQrHQC1UuWQwUi14jOSETMBaqoi67mh1S2tydePuEkDPHM77zz96sodN03OTMoNu2qnLubmFboFyswVJmTMQAl8k4eTSgY45rigFkp5XHHQW/KNFUbOag5pKPIGh9/8xQc/9S/e/p674/zZU+28pNcxzGk3WC1TCzFEiSIhxrDqBkmIMZbGQFQFV/tSgJ5+eS5omiV8w54JIGKLcYC/EgyOYKpJBq5HgTpDGYhrOXEMAMu8sbkSvBlTIz22+IQIUCjDaQyG1tvffOPv/PJdDx1srCxeXFjx5jJF7pRFzTlmLkkN5TK20gd1Rr3kAlGlcwSbsAHUS+NjvTIIpQBkzx1ZmlvUXdt19w4PFGTNfhLfhtQCjysjQhv5JlEG6BpqTZlOIaFisbCS0Am98glmxsQqbu8O+42fe9dH3reLZO7SxQsu8XAKy10kgQpDVbjP3JpCokgQeOoW0K+2IxFV8Yqg66Orve5AOt5EkUvOXC7OXu7s2Z7unEmxGbbW2s/9yGM2zvkZoUHwzLHyFkvCZJkJsECxFRWelYx1wK6MpFKvg+wTpDhw3cy//Wc/enD28tLCGYNj9qZGffepERIC1MiqghY1RBGVqqa+h3T2nk5FOdiYjNiYAeilRU3hGSud/OT59v2HajsmU8BvSNvu5+6PMsKbWw0G9UkCJoXRmqY8RASoxUIZBlaQ9aNAI+s+sE4VJxGJutkp2rt95eLCZc8NglqfV2WmAna6CrKX87LKuqiiotCu6QcjpiKia/snbd4367vJMsrU46fbJtvTFMNJ5mH6/ohmHVfihULJm41UL0Sm0KJc9rJpq75e0xoLiHk0b3UrjQwRdQvcTVWIXZ+j2Ys5tET8aYSroyYiUqqXdVfBpiYil40rXj/fiVHSxLx3usXWB36TymftDRlAjpmhZWenqscQqZjzpCZsAmM1DOJAw+HYgI0awqPUmzkx0Qh2pjpwPoUIk8Qqv1jF8GaiJmpKSkNJUFGLUUPXD8bgErTeMPQ0HfUD6atlFyZggM7NFwFIa5R4awfl3oobSusOF71eTbMOGqE7iYhY30isn1QshCAiZATTNfxLmMJitBCjlZ57lY4zERFVAkYKQMW6FS9rMoU0tg2ZWUkYWNtDDm6p1YkKR0nVrmCrbuhmSpQGvwBVlYEF1BW7Enxpp2md9TgSZewldbt6ZBWeilFMpCx87E/rE6wSSy8coUoRi0SJ4hJbS4EBEdRUVaw0G1toZdZdLtR3IUTALXeiiOUdk8ilFVjP9RxOzlz5CpBgMIVxf8UOYGrEHuzIjInU+kqLNjLsTBQcuxAYRs6X2oO01PViRkqwshSyNxxKpM5sbe2emoqYqkF0NRLs/qBAVBnpYnY7A9gml7/BASYCUcnzKKrkeEs+vcfYxjPj/LCCyJiIQNo1/pVCpQTkDUrkzCpLtXEzI0cCmwj58vQkZqamXju7wOQANSaUWfSuU9k3zqpGlFivjqmyzTAREuGytI9Wu0FRycALXqFaKk0MzcrxxXXUDdQMBnNALoEMlEcRC45qulEE0P/sfGVZcgJrWymyOQMP8iCZ2dVK5cE2iuLYc/z7mMMkAonLD92x81//Lz/y/rftVslLeh3BDKYiKhpFYoyqohJjjBIlxigxDuAKphApAVGTqDFo9yWqKmVSTKUixFx1uzZVhdJKO44Ma0YSF69WBTFxaKsWwARBhtpPkfm6y/vauQ0Jv9dkDExkICk6O6brv/R3bvnAw9nsVOvrj+UoeznAqVooClHt5TVXqTVlcy3VUMT+mzA1iRqieEd9IZt2yQ0koiPZwVuEA6rl4Byp0oW5VlnjcSVY0ED3ATNj5nWBGoOxaUdDS/0UKDpUpBgjEBtRoumUW4EZCRtGwXEOMKPg2EluBH7/D+//+fdft3e6szB3MbWpHAp4mAIKoxAsRhArlaPYtQEERBiRRukWVZZnN40SggrTaopgdS0qnCSi1FNBg8yR8S1HbBVdIoqGbKqeGeLx06FME47nx202ENtgVTIsUJzTZPcQ2mwAIZnxhpyJRlo0tkCUREslX7l57/Zf/ej1D9+ZdlYur7SNUMs7CCGs+uaKKKJqZCgj3H6XJqIkgA3gXyXzyhRUxSlV+reM0638a/+jbl4JrzaZ1EjOATY7zc7x6+dbAJtdaSA2xjUc4ZWSsiXFRW0gVRJau0pEJdmWkM/VlMqWGgNL1yPmrdT7D//YzR9/366p2srC3GWihKpmD134rBvVqqrEEr8fFHYkdjCDMfe8MZKoEk0VYqZmqxVzpQwNMZaO64hmyxu2PayKIdS2T2aiulB09m2bNvGnL+YA9ztXm6n68j2PdUxf1hFerZHB8guKQOrEqeunhqmam4SfoLBIcP0tRJWQgFjylXtu2f7Lf+fme/ZZp3NpoeOdywwqClVhZ+x6hU0EIIrFqFay04m6KLGaWTRjUrE1pRYCiIqKxtJvpSpXpGowEzMXaCCRMf7x1/hA5pyZmB3aN/nqa5eAsHPaX7rYPj+fw7l+u9ff2mc0qg/4AaO8nsM0bAbgNZ8XmVeahaqWzcfKPs2q6jOq73RhXshRHw/dHCOG4iPvvuFXfup6hPNzi3DsCFL66wYThVqvYTUBbIYiqkWYM6yNVxUiZjFSEO1vbadkpQAC9xPwKzBJDSomVhX7Vktjk46QEUFFbXvTHdhbe+pVAvyunRMvnVjqhMBZAxI3hKP7B3OzGbHBWIEAYi3QORW9JQMYLIPVWe1GD1Io94daBjMLd9/S0Pz8yrI5gmkokyci0cxMNRRBRHptMcw0xhAlaoQqREp6lcVoIqQKiSpRTbU3mgCJQNRMTcTKo2Is41/TEqhTNZTJDNr8IJgRs5mGu2+ukUlRJFmS7Nk9+eQryxUMCRpwstctALgKNLQCvhjJ8sl88s6Uupa4rPglcDSp7fO+5rTTbwWcWkKIneWik1uEQl0FbRKZKlRFSi6trEEj1EQU1Tf7nHcGyCk0hLi2y7+JqETrXlpNe3kZWBla6/BOExusgxImMXUJ9O5bJ59+fgEIu7ens9Pu2aMLQIIKqdhCQ6uN6wNGriMyLrVQ57yEC+CMlGQ13QHTqGkTtb0Mi9XOBNUJQunHimlRxFASl7UCL2MVXZlEBXrwAlVTuArEpBApRIJpUJMYqwQ7CORgDJiYRiPp0XFFBVb+KqqipGpBaExD9HWRHDKJuOdg47qZ7PiZNpAfvL7easkrZ1rEpOaxiX4b/TyoK1RBVXMwmIktH8szaTowr7YOMYKKycSNdeWANeiKGUzUQtBQaCgq1loM0lUUFgqVaH1tXdGNYctFAq1o5haChBDLeosBNzRWLFArYTeJlS5SRSwLNXTL0S8Bplxz+sGHGnlr+XKrAOi2/RNPvbxQFJE9X0FEzeMSnuPWkVWsBU6Xj8c4Bwajyv4wYE6dBDSvd8m2pLJ31lcJBlQcWbFe3UoMItFMEYJI6XOSdqHNUmubVkiySfmzmkQtQhBVAqEaUzK1UmDSrYUxJRWolD+jPBbrMzaGV4MZiMlieNMtyf6dePVcaMeGd/7AdVNff/JC6SwQdGvldf0C6Lp3RMS2TjeQnnkhY1YHgJwPK5h/dZl8IlaWcfXwAKVJmT5UgykTGFbqh7KjmCp15zJUEIMUQYuIPGqIqpX5BaAgi2pRrNQnAoMCYqV+CWIhiknZiaMCylQpRhW1ctmUZltRrQdRjRGiVSf84cEaAVsRPJuKm2r4d947Md+Kh48HmNxyQ70G/+yROXLO+phe/XDQmKT8yCrJcRtw9PUnIkJJchJiv/BSrkuErJc5IrAyI0SZuiVLphkhAZKe8Y+xYkZpOfpSjq8F1SJqEbWvdWqpT6QQieVCiVq6PaVGF1MAWqZ4e+6pQSpynKlVa6X62VRUomJMl4NRQyZGdZPifQ/M7Ju10/N47WwOhDcfmnrm6EIewc7ZOuUeY8ogV9HQodW3gfSUTNhgyDycE1nxi8+3a86v7q9iMJhGxYTM3FNXUwOXVUoGygvJQwii5aCXZStRRKJKUJVed2QAbIoY1QTVTBYNolE1qJaOpvZa3XZXjfXQTyPV6m1KKiQRqlYGcRtCL71xdOSlyO++MfuhO1hNjp33Cy3xbPt3T3/l6bMgb3qFdVdXyowrSdSG1LvpSQeH+ZeL/DXAVUnTan0xi8Tt9zTr1xtiQd3dfUJRxCiqLFrS10rusklUVaiZruIOZIZy8lZWQ3XVvVEV0SjaxfDXuqKGqoWoQtTEoFp6Dptv+VclGkS42QgfeHgGIYQifeFYC5A7b55c6PCJMyvOw6502ydGtyRRqwpE7bagHbdjDBPIlBwtt4rd2xsTdba2XfzeiouJsnR3XyIArKSuM/vWCXgjMSMHUC1JHVhVo6iWkzp27SwUpqv7CpEamahFlVhGa7HSQGImZkEgYnkMqoBFsHRzuGRgMYhZrGQWpQzjQGowi2QyNgrr8irNQ/Kffnj3zqlCHZ25gKNnAoAHbtv7rWfOAAlbsirzUb7M0JhzWRk60gZsKSNvZjq/tHL/we0GbZ+Jy8/E1DfEdJVGQNQOnfruZPrOTEwcmVE8fDTkaEabl9zHaCLS5TP3ZWv74kVRVVERDL/NSNVikF55TIk9d1W/qmpvH5/ypWUoLBumbU1JyKUaO++6d+LhOzPRTs0nTxxt5wHX75x0CQ4fueR8plWd8IabHNm4djWD31Ubn0sjIlOQ59PnWhNNf/eBpikuPdMKrxGnfhXsJSZK2rQ8+0Aj28Oag5LkGy9c+MvHV5R3FtJSW8NO6BIapDf8ZihVk4FMYUoi0O7brEo7drPkPcZWuaSkEkDFZVMzEykbuNBIm7mmkwYSzfO7b6r/1Nuni3yuzsnrl5OnjiwCnXtv3/7dwxdEubSItna/s3WgCFrDKOilJPtLU9aIhoYKptdy80AgZXb+O8+desedeyZqbCE99+0FrDiXQasSayUjCxrT9p63TKMmiMJJ9pWnLjz2vExPTDoLUlZClhWkQnmExm62EExGZqQl1ccgXa+mogILIlBR4LqOk8Kk9AKqgKVcEBArLTC0So/14KY+s0+OQGxl0X28frv/6Ht2kiwWwi5Jv/3ifKsju6bqBnvu2Dz7xCys3S1wjPLpAgUoy4hsnAra5FaeRsZcu7xoz5+c/9n37Vduh3l/8ZHlJJ8kikqxRHmcUozKe+O+dzQN8GJIm3/xxMWvHda0uS2RCImxRAvEgqCvQW3ZDsakhHfMpHR8es1gBAIL2nNDqYIssSqRSvNYFUKXR+to5LnsUBzhnBR+5zT94genZvxKIbWJul1YSJ56NQfxTTdve+7lOS1rC8k27cv2yJPWSxvwiMM24U71dSY2ReGS5NHDc7NN+vi795kWK2eL09+43AhT5cZITGQExxSsaNyZXP/2icIKApuf+S9/femzj7Wjq6lRKFJVAOYd9TVPIwNKkkmlGVW7DUGqriDoJil7vn21uwtTv2Hs0TTLgdY+HvqQpq5JkJ2T8Vc+tG/fpMA4STVJZ77y5PJyx81ua7bb4bXzy8TJqNqT1bz8WGJ6JYer7phlBCODEPj//uKp994/+9431U24eFVOf2upjklLgxkcOSaXoNbOF5v3+NmHmhrbPubO+689e/k//lX7YnuylgbWaosj51wfKcTW7xm3DrG6RJ8MTL1GeBV2wuyYvIOVW18NID0EY68S8p1N+7WP7jyws51rBo+JJDn8ijz+8oJLw3Sjcfz4PHxyZT2CxhnhyroO1ywOWYg1gXtZSeTp7Hzxyb88/is/ffChOyZyKxaO5Ke/OV/LJ0uoWcmIzEnWardn7q/t+aFGsNzUOE2ef33p333p7PMn02xiJsuiaVCNIG9MJRQBFiLSbpK+fBtB2ISMreTLMbgkJTCX+l+tizgSjGHeFCqSOE0a/tKKhyX9xflGxswxj9fPut/62Ztu3iGhpQx1iIud2p8/dl6MJieyy0ut5WBUbe5HI/X++DC4i4sTkVttW7mKvm2xU2SJ/xjMu+TI2Xy2iZ97367XL+Wvn8vzS64415rZM21NEY2OymoaRHQmbspqE9nSaysUXJLVVwo+fKx1YYl2TE3snuGXTxZHzgbPUAk7JtMHDqUxFAomssFuRUaOrRX8914tohITm9oNO/1dN3CMpRYq03TkTRO2NPUXWvaF7yaPHl4wJ7BesoKYUylad98w86sfvW7nxFJYcewNEpLa9Ge+tfT0sbavwau1WgT2Bt1wh8uxpRmlAGiNAHBFfUxWk7RwxHjxyMqh6+sf+pFtnTx5+bX5YpGXz6xM75hKd6UxFhAwMzmXW2zsds0d9daFTlw29obEnzkfnz/SXgj+4gKdW1hhylR157S//1AWQ6+ixcrKegIRkzNmp+3gv/dqHgVMbKo37k7v2Z/kQbpEN0sTpLXsQmvyq8+FLz/ePnKuUCY2V7VXIaiRxdZ775/9bz+0p8HLRQ72JqQT9foTr/BnvnkOSQKhIooSg0qAl4b7fK7X0XF4m+VS/fQ65/Y28KUyAKzYfAP7AI+l2oEUxIXy88cXHzg0/fCbsob3L56IxYosnlpJydd3pkpBzZjrziyGQFM2va8Ri9i5FF3MqO5yw/HXWxcXO+Y9zJnSzmn35jsSzdvBuGQjM7lyv4qS1+MNSzH7/qt5NGJmE7pxt7/nJo3R0oTIJbnWjpzDI8/mf/Xd+VfOaIccO0dllwMuHHMMnHn52Z+44WPvnaW4oMJEpkT11L12ufGJz73eUpAJ4EAESDkJBjg3A21zx8awq3BnKQDu25l4K4T0UbRJ52y5pUdeD28+2LzntvTQTbUTp/O5y2HpZJALqO9KkhmOCMEKFtbAWpdtN01m29LWQicuwiu5jKTsk0JmsJR41+xEvZ40fcrM3nPGlpCSKouYwRm1gvv+kTwoMdjUbtqT3H8wWSiSY+eTJ17sPPL0yl+/sHL6UghacwkMUlJYPbNoKjHcuj/5zZ+58Ydu9UVrDpwSmynXiZfC9P/1mROn58U5r31I+xi0eBO6hPv3seupoN5GRzbe/ezWvI2OMhhmRs67i/Ot4+c6b71l5uAueehNs60iOfr6Yme+kx8nZtfc1mDjqEJIjbVwK9lumrq5yT525trSMVNl50DOnCx3wjMvL798Sk5c0EuLVuQM5zTJ1GXRfG7enC/Mf/+Vdii75hApJcde169+P//miysnzrWXOg4+Y5eCYGVrHSaQSizqqX3kXTf8+oev2zOR5yuREg8Hbwn5TnDTn/js6edOFlx3iLQOx5KGAYKx5nN403jf7P/USMf6TCM2e+vnuRBM4QzwjFjYfTfXfvNn9k835iVJn3yJP/WV14+f6QDJxHXp9MGkdrPZNGs0kQ4Lyr0F5JJffjUuHWvFBWObcgzhTkmJgyaAMGvikdVc5s0DRJQwAvzZeTONMGYmE1MTsEuIjaEQs7KzoTEyI9UiAPHhu/Z87D2zt96Qd1oSIswEBjXvSWJS+8NPz3378EWXZaJCGJ0+2/zuL30QBff7j8Ob+PAWY+H17oYT9kWxcPtNE7/9sVt215bNZUqNv3hq7rNfv3D58iLAzT31qbt8fb+nxAWNZWMf8uxrCeWcv4KFH3Q6l4PkApijRBMmJpiZEtRIy7ZjWplR56kqUipDExAZiEsaG5sx+QhYaAPu7kOTP/Pe3W892AjtVlEEcsRkohwKcRwknf63nz73tWcvclorQY+R+zaOp3Ntkmwx4AURcOXd3AZa3Jmpd7Xzl/XZly/fddveG7cR29Lb75l8+J49ZHz2QmdxTpePcee4xAUh1nTCJXUPJ2KdmIZsp6/fwPW9Ppt2BKioiiEYRUAjkYCZ2FV7QqDcfKxEcahbyEUgZSREXlQ0Fs7Cfbfv+LUP7f+lH9tzYLbo5C2RqsuVeka01HML9f/zP5/65nOtJHWm0tvGcYuKfjTnbrg9+ugV0Ns28sqkChDMgwoz8pREaU81/O98/JYffTDrLCx5TrnZPD8v33xy8YvfmTty6jyg4Frzumxir6/vTpIdHGsqFBABAjFToLgSZcXJkrYvheJSrjksEsAGLduEkQeBKSZSmGrVMkBUEQ3o7JppPnzf7vc8OHP7DUlCRXs5iBknVrFOzalJs+FOzM38H598+fCxlqs5DehPGv9Xeq3ZzNPW1JjZ5sZ6TIwtqFpHJBIDWfgH797/sZ+crfui04nbmvWJiYkLS3j0mcvf/O75w68uXFouAAaTm+b6JNV2pH4C1DQ3xa4JSaI5Tn2qUcKiSgdmjs1RC3E+6lyMLYkdiwWFDrQAUAAy1azde2j7O+7f8eAdE3t3wGKxstzKA4G1TItEUBGc087EZO2Jo+5fffKVMxdzn9ZEpX/HqmF+bkl8L2GpVTR8vSqgfmaOUZ9LacMC2Opk35hK02WKwWK458D0b/zM/gdub7Q7SxIic5ZmHKl+eTF54cjCE89dPvzqwonzrRA6ZSsMwFBLfb3BKcG12BERrDCLpEZqXoJHqwNp9y6ZZo0b90zed2Dq/tun7r6pvnd3g6lorSzmedUU2UwklmCo05AnnjpW+8w3Fz/1pdOt4Hw2oqv96JFl0p55UBsvAOt3FVe5ubbBhs5XYYRHCIKdSq7NNP3YB3b/g/cf3J51lhfbBSjNpJ7V0iwTYKVFZy8UL5xqv3Js6fS5/OxcfnE+X15Bu1DVJUD6ejlywmlWS6cmaWba7ZltHNg7ddv+mQPX1fftTKYn1GRpeSUWHbFgRBTIYFqWjxdBYoGaT2oN/+Sx/BOfOfPMq5eRGVsC8WNcwTVlLNSn5XX8NrJ9hysNCGDib2BT+6oOxYhdFEss2MG9tZ//yf3vfGhyW5Z3Oq6gAFEPl2aoZal3nn3mknowt7gSVnJeKTC/EvK8UIF3aZqQ95p5mq4nU3VuZOaTyA5WSKdTdPJCNCgxCaSkfUFhUGMzE217MHPj1KL+2bcufvaRs608uCxRKfs9lj6UrZegXysA6vpdA6TbdQTQnxQr/8LJ1NXZ27E5y8EDuQJBHGJOQOf+W7f93AcOvOPNM5NupdUqgnn2NWMjmHecJM5555zzntM0Zee7+8anRqRFXnRyCTGEqGplg0TV1SYQZf2YRI1Ro5pCSWPCPsvcxWX5y28t/enXXj99cZF8nSg1C113k0Zt4T4iVCKjYTS0N5jrjZsN7gHmJzd0+ftL7mlsH6mNxMbdUucSZPaaC6D33zb5996150cf2HndbBZkudMRcN17z8zEXG5gAiLnE+ccEWs3nSGhQJdEZJAQipLzUxaJVLwtUREh1SyhmGVnLshXH7/02UdfP3F2Gch8moiG7uZl1g/UlGXIWLut+BoBlOSQEazZ8dVdA7HbJgRwBStjfQFQFZRauaeRGCjmBsiNe5rvedvedz+0800Htm2bhogWRYhKRI4dE7NPk8QnRNQlvJXEUpTJMjERLQlGolptLEyQxGeOaosr8fs/WPjyX1/6xjNn5hZyoOYSM0Q1T0YM9Njd6+wSjA1XwBULoLkJT2Z4SWJEGwr05/9HHG4DN6IAKQHEINIYIkwc+zsPTf/oA/sevGvXnQfqu3ckaVLWcXDBzPAwDhpijKZlqb6YkSooBDMhJiIBqVFaCF+ez1842n782fnHnzn38sklIIIT9gZlVQZbt4SJys4v64M5w1JZs6P2wO7zIxhGsOGRIaK/RQF0F3q3izkRMUPMrBAADL1+tnngwPSdh7bdffO2Qzdu27lnamYynahT4shUzAJMAZKIooidIl/uyOKKXrrcOX5y8YWjrZeOLx05MXf60qLCgIS8Y6ZuHrnq7TUyk0Ij9o7Afx0B8AgBDM2C0QIYqXBGFfkPCqB/N+Cy38ZaoTAzlSQ6DQaLZUDnU9492dyxrbFtJt02XatlvpaRdyxAux1XljsLi8XcUjG30L64UHQKAgLKGv7EOTD62KDWq43cGkdxnGUe35ltzb43a0dm8wKw9XyskQJg9Lpe0KCD1vcZEfX2iumemrlUCAYi5srisli0KFVWGNoNBazvZ66Kpx27MuCCoayvr3I30Kqxbl8WfiMBVO5cv7cDG5UfGc2BqD7sP8bWagBOmlilFVd+Lq27bTj1KHbjLXBvNY8R2xhnuXtElzRnve04S1h9+DkVpaKoiCroI8rZenNrLfoyDnpZo6tsRBuegW1vzPpLnce9fC1LBgUwpqP2iN11hugg/XDSwG2NTbHZ+nk32ygfZ2Da3Hlo7b8bPpRhcLBpVKOzYS7DwLXWyyr6tYytDZ5zQ/CVxn6ftnLsVlKhoK2cZ6Bt+/iHGtnjnTYxMrT+4Zsi5157/c28rgngmgCuCeDa65oArgng2uuaAK4J4NrrmgCuCeDa65oA/v/1+n8BaHSE1JJS0YIAAAAASUVORK5CYII="

# --- إعدادات نظام الإيداع من داخل اللعبة (زي بوتك بالظبط) ---
GAME_API_BASE = os.environ.get("GAME_API_BASE", "https://diplomacia.com.tr/api")
DEPOSIT_UNIT = int(os.environ.get("DEPOSIT_UNIT", 1000))  # مدى آي دي الحسابات (لازم تفضل آي ديهات الحسابات أصغر من الرقم ده)

# --- إعدادات الاستثمار التلقائي ---
INVESTMENT_RATE_PERCENT = float(os.environ.get("INVESTMENT_RATE_PERCENT", 10))  # نسبة الربح الثابتة (قديمة - لسه موجودة كـ fallback بس مش مستخدمة في فورم الاستثمار الجديد)
INVESTMENT_TERM_DAYS = int(os.environ.get("INVESTMENT_TERM_DAYS", 7))            # مدة الاستثمار بالأيام (قديمة - fallback)
INVESTMENT_TERMS = {7: 5, 14: 11}  # خطط الاستثمار الحالية: أيام -> نسبة الربح% (سارية من هذا التحديث، مبتأثرش على الاستثمارات الشغالة قبل كده)
INVESTMENT_MIN = float(os.environ.get("INVESTMENT_MIN", 5000000))                # أقل مبلغ للاستثمار

TRADING_FEE_PERCENT = float(os.environ.get("TRADING_FEE_PERCENT", 2.5))  # عمولة GNID على كل صفقة بيع/شراء
PRICE_BAND_PERCENT = float(os.environ.get("PRICE_BAND_PERCENT", 40))  # أقصى نسبة يقدر أي أمر جديد يبعد بيها عن السعر الحالي - حماية من التلاعب بالسعر (زي حد يحط أمر بيع بسعر بخس عشان يهد السعر المعروض للكل)

# --- تحرك السعر تلقائي بناءً على ضغط العرض/الطلب في الأوامر المفتوحة (كل 15 دقيقة) ---
MARKET_PRESSURE_INTERVAL_MINUTES = 60  # كل قد إيه بيتحسب الضغط ويتحرك السعر
MARKET_PRESSURE_MAX_MOVE_PCT = 1.0      # أقصى نسبة يقدر السعر يتحرك بيها في كل دورة (فوق أو تحت)
MARKET_PRESSURE_MIN_LIQUIDITY = 30      # أقل إجمالي كمية (بيع+شراء مفتوحة) قبل ما نعتبر الضغط إشارة حقيقية - عشان مع قلة اللاعبين حاليًا، شخص واحد بأمر صغير ميقدرش يحرك السعر بمفرده

# --- مدد سداد الديون ومعاها نسبة الفايدة (أيام: نسبة%) ---
LOAN_TERMS = {3: 5, 5: 10, 7: 20}

# --- تسجيل شركات اللاعبين (مصانع داخل اللعبة) كأسهم متداولة ---
COMPANY_FEATURE_ENABLED = False  # الميزة مقفولة مؤقتًا (تحت التحديث) - الكود والبيانات موجودين لحد ما تتفعّل تاني
COMPANY_TOTAL_SHARES = 1000  # إجمالي أسهم أي شركة لاعب بتتسجل - ثابت لكل الشركات
COMPANY_OWNER_PCT = 50   # نصيب صاحب الشركة (محجوز، مش للبيع فورًا)
COMPANY_GNID_PCT = 10    # نصيب خزينة GNID (محجوز، مش للبيع)
COMPANY_MARKET_PCT = 40  # النصيب المتاح للطرح العام على طول (IPO)
# جدول القيمة الأساسية حسب مستوى الشركة - بيتاخد بالشريحة الأقرب لأسفل (مستوى 137 ياخد قيمة 130)
COMPANY_LEVEL_VALUATION_TIERS = [
    (0, 5_000_000), (10, 15_000_000), (20, 30_000_000), (30, 50_000_000),
    (40, 75_000_000), (50, 110_000_000), (60, 155_000_000), (70, 210_000_000),
    (80, 280_000_000), (90, 360_000_000), (100, 455_000_000), (110, 570_000_000),
    (120, 710_000_000), (130, 875_000_000), (140, 1_200_000_000),
]


def compute_company_valuation(level, capital, daily_production):
    """معادلة تقييم شركة لاعب: القيمة الأساسية حسب المستوى + (رأس المال × 70%) + (الإنتاج اليومي × 7)."""
    base_value = COMPANY_LEVEL_VALUATION_TIERS[0][1]
    for lvl, val in COMPANY_LEVEL_VALUATION_TIERS:
        if level >= lvl:
            base_value = val
        else:
            break
    return base_value + (capital * 0.70) + (daily_production * 7)

# --- يوزرات تليجرام بتاعة ملاك/إدارة البنك، تظهر للمستخدم في صفحة "ديون" ---
DEBT_CONTACTS = [u.strip() for u in os.environ.get("DEBT_CONTACTS", "").split(",") if u.strip()]

# --- بوت تليجرام (مستخدم للتوثيق بس دلوقتي - راجع send_telegram_dm تحت) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


# --- بوت تليجرام لتوثيق حسابات المستخدمين (verify) عن طريق ربط حساب البنك بتليجرام ---
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")  # (اختياري) قيمة سرية لتأكيد إن الطلب فعلاً من تليجرام
_bot_username_cache = {"value": None}


def send_telegram_dm(chat_id, text, reply_markup=None):
    """بتبعت رسالة مباشرة لمستخدم معين على تليجرام (مش الجروب) - ممكن تبعتلها كيبورد أزرار (inline_keyboard) اختياري."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data=payload,
            timeout=10,
        )
    except Exception as e:
        log.error(f"فشل إرسال رسالة تليجرام مباشرة: {e}")


def answer_telegram_callback(callback_query_id, text=None):
    """بترد على ضغطة زرار (callback query) عشان تشيل علامة التحميل الدايرة من على الزرار في تطبيق تليجرام."""
    if not TELEGRAM_BOT_TOKEN or not callback_query_id:
        return
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
            data=payload,
            timeout=10,
        )
    except Exception as e:
        log.error(f"فشل الرد على ضغطة زرار تليجرام: {e}")


def send_telegram_menu(chat_id, site_url):
    """بتبعت قائمة أزرار البوت الرئيسية (/menu) - فتح الموقع، الرصيد والإحصائيات، وإزاي تعمل إيداع."""
    keyboard = {
        "inline_keyboard": [
            [{"text": tr("bot_menu_open_site_btn"), "url": site_url}],
            [{"text": tr("bot_menu_balance_btn"), "callback_data": "balance_stats"}],
            [{"text": tr("bot_menu_deposit_help_btn"), "callback_data": "how_deposit"}],
        ]
    }
    send_telegram_dm(chat_id, tr("bot_menu_title"), reply_markup=keyboard)


def get_bot_username():
    """بيرجع يوزرنيم البوت (من كاش، أو بيسأل تليجرام مرة واحدة) - مستخدم لعمل رابط ربط مباشر."""
    if not TELEGRAM_BOT_TOKEN:
        return None
    if _bot_username_cache["value"]:
        return _bot_username_cache["value"]
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=10)
        data = r.json()
        username = data.get("result", {}).get("username")
        if username:
            _bot_username_cache["value"] = username
        return username
    except Exception as e:
        log.error(f"فشل جلب يوزرنيم البوت: {e}")
        return None

# أيقونات جاهزة يختار الأدمن من بينها بدل ما يكتب رمز السهم يدويًا
STOCK_ICONS = ["🪙", "💰", "💎", "📈", "🏆", "⭐", "🔷", "🔶", "🥇", "🥈", "🥉", "🛢️", "🏦", "💵", "🧿"]


def format_money(value):
    """تنسيق الأرقام المالية بفواصل الآلاف، من غير أي كسور عشرية - مثال: 1000000.5 -> 1,000,001"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return value
    return "{:,}".format(round(value))


def telegram_link(username, has_username=True, chat_id=None):
    """رابط تليجرام قابل للضغط ليوزر معين، بيفتح في تاب جديد.
    لو الحساب موثّق بس مفيهوش يوزر عام (@) في تليجرام أصلاً، بنستخدم رابط دخول
    مباشر بالـ chat_id (لو متاح) بدل رابط t.me/الاسم اللي هيكون غلط ومايفتحش حد.
    ملحوظة أمان: username هنا ممكن يكون First Name حقيقي من تليجرام (مش يوزرنيم مقيّد بقواعد)،
    يعني ممكن يحتوي أي حروف - لازم نعمل escape قبل ما ندخله في HTML خام عشان نمنع XSS مخزّن."""
    if not username:
        return ""
    safe_username = html.escape(str(username))
    if not has_username:
        note = html.escape(tr("telegram_no_public_username"))
        if chat_id:
            return f'<a href="tg://user?id={html.escape(str(chat_id))}" rel="noopener" style="color:var(--gold);">{safe_username} <span style="color:var(--ink-dim); font-size:11px;">({note})</span></a>'
        return f'<span style="color:var(--ink);">{safe_username} <span style="color:var(--ink-dim); font-size:11px;">({note})</span></span>'
    username = str(username).lstrip("@")
    safe_username = html.escape(username)
    return f'<a href="https://t.me/{safe_username}" target="_blank" rel="noopener" style="color:var(--gold);">@{safe_username}</a>'


TELEGRAM_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
WITHDRAWAL_LINK_RE = re.compile(r"^https://diplomacia\.com\.tr/profile/player/\d+/?$")
TELEGRAM_VERIFY_CODE_RE = re.compile(r"^[0-9a-f]{8}$")  # شكل الكود اللي بيتولد بـ secrets.token_hex(4)


def is_valid_telegram_username(username):
    """يتحقق إن يوزر التليجرام مطابق لقواعد تليجرام الحقيقية: من 5 لـ32 حرف،
    حروف إنجليزي/أرقام/underscore بس، من غير مسافات، ولازم يبدأ بحرف."""
    if not username:
        return False
    return bool(TELEGRAM_USERNAME_RE.match(username))


# ============================================================
# الترجمة (i18n)
# ============================================================
LANGUAGES = {"ar": "🇪🇬 العربية", "en": "🇬🇧 English", "pt": "🇧🇷 Português (BR)", "tr": "🇹🇷 Türkçe", "id": "🇮🇩 Bahasa Indonesia"}
DEFAULT_LANG = "en"

TR = {
    "brand": {"ar": "GNID BANK", "en": "GNID BANK", "pt": "GNID BANK", "tr": "GNID BANK", "id": "GNID BANK"},
    "my_account": {"ar": "حسابي", "en": "My Account", "pt": "Minha Conta", "tr": "Hesabım", "id": "Akun Saya"},
    "transfer": {"ar": "تحويل", "en": "Transfer", "pt": "Transferir", "tr": "Transfer", "id": "Transfer"},
    "market": {"ar": "الأسهم", "en": "Stocks", "pt": "Ações", "tr": "Hisseler", "id": "Saham"},
    "manage_stocks": {"ar": "إدارة الأسهم", "en": "Manage Stocks", "pt": "Gerenciar Ações", "tr": "Hisseleri Yönet", "id": "Kelola Saham"},
    "company_apply_nav": {"ar": "سجّل شركتك", "en": "Register Company", "pt": "Registrar Empresa", "tr": "Şirket Kaydet", "id": "Daftarkan Perusahaan"},
    "admin_companies_nav": {"ar": "طلبات الشركات", "en": "Company Requests", "pt": "Solicitações de Empresas", "tr": "Şirket Talepleri", "id": "Permintaan Perusahaan"},
    "admin_dividends_nav": {"ar": "أرباح المساهمين", "en": "Dividends", "pt": "Dividendos", "tr": "Temettüler", "id": "Dividen"},
    "admin_notifications_nav": {"ar": "إرسال إشعار", "en": "Send Notification", "pt": "Enviar Notificação", "tr": "Bildirim Gönder", "id": "Kirim Notifikasi"},
    "notifications_title": {"ar": "الإشعارات", "en": "Notifications", "pt": "Notificações", "tr": "Bildirimler", "id": "Notifikasi"},
    "no_notifications_yet": {"ar": "مفيش إشعارات لسه.", "en": "No notifications yet.", "pt": "Ainda não há notificações.", "tr": "Henüz bildirim yok.", "id": "Belum ada notifikasi."},
    "admin_notifications_title": {"ar": "إرسال إشعار جديد", "en": "Send New Notification", "pt": "Enviar Nova Notificação", "tr": "Yeni Bildirim Gönder", "id": "Kirim Notifikasi Baru"},
    "admin_notifications_lede": {"ar": "الإشعار ده هيظهر لكل المستخدمين تحت زرار الجرس 🔔.", "en": "This notification will appear to all users under the bell button 🔔.", "pt": "Esta notificação aparecerá para todos os usuários no botão de sino 🔔.", "tr": "Bu bildirim tüm kullanıcılara zil düğmesinin 🔔 altında görünecektir.", "id": "Notifikasi ini akan muncul untuk semua pengguna di bawah tombol lonceng 🔔."},
    "notification_title_label": {"ar": "العنوان", "en": "Title", "pt": "Título", "tr": "Başlık", "id": "Judul"},
    "notification_body_label": {"ar": "النص", "en": "Message", "pt": "Mensagem", "tr": "Mesaj", "id": "Pesan"},
    "send_notification_btn": {"ar": "إرسال للجميع", "en": "Send to Everyone", "pt": "Enviar para Todos", "tr": "Herkese Gönder", "id": "Kirim ke Semua"},
    "sent_notifications_title": {"ar": "الإشعارات المرسلة", "en": "Sent Notifications", "pt": "Notificações Enviadas", "tr": "Gönderilen Bildirimler", "id": "Notifikasi Terkirim"},
    "confirm_delete_notification": {"ar": "متأكد إنك عايز تحذف الإشعار ده؟", "en": "Are you sure you want to delete this notification?", "pt": "Tem certeza que deseja excluir esta notificação?", "tr": "Bu bildirimi silmek istediğinizden emin misiniz?", "id": "Apakah Anda yakin ingin menghapus notifikasi ini?"},
    "flash_notification_sent": {"ar": "تم إرسال الإشعار للجميع", "en": "Notification sent to everyone", "pt": "Notificação enviada a todos", "tr": "Bildirim herkese gönderildi", "id": "Notifikasi terkirim ke semua"},
    "flash_notification_deleted": {"ar": "تم حذف الإشعار", "en": "Notification deleted", "pt": "Notificação excluída", "tr": "Bildirim silindi", "id": "Notifikasi dihapus"},
    "admin_dividends_title": {"ar": "توزيع أرباح المساهمين", "en": "Shareholder Dividends", "pt": "Dividendos dos Acionistas", "tr": "Hissedar Temettüleri", "id": "Dividen Pemegang Saham"},
    "admin_dividends_lede": {"ar": "أدخل صافي ربح الشركة أسبوعيًا، والنظام هيحسب صندوق الأرباح (صافي الربح × نسبة الأرباح) ويوزعه تلقائي بالتناسب على أكبر 5 مساهمين بالكمية.",
                               "en": "Enter the company's net profit weekly, and the system will calculate the dividend fund (net profit × dividend %) and distribute it automatically, proportionally, among the top 5 shareholders by quantity.",
                               "pt": "Insira o lucro líquido da empresa semanalmente, e o sistema calculará o fundo de dividendos (lucro líquido × % de dividendos) e o distribuirá automaticamente, proporcionalmente, entre os 5 maiores acionistas por quantidade.",
                               "tr": "Şirketin net karını haftalık olarak girin, sistem temettü fonunu (net kar × temettü %) hesaplayıp miktara göre en büyük 5 hissedar arasında orantılı olarak otomatik dağıtacaktır.",
                               "id": "Masukkan laba bersih perusahaan setiap minggu, dan sistem akan menghitung dana dividen (laba bersih × % dividen) dan mendistribusikannya secara otomatis, proporsional, di antara 5 pemegang saham teratas berdasarkan jumlah."},
    "top5_total_shares_label": {"ar": "إجمالي أسهم أكبر 5 مساهمين", "en": "Top 5 Combined Shares", "pt": "Ações Combinadas do Top 5", "tr": "İlk 5 Toplam Hisse", "id": "Total Saham 5 Teratas"},
    "weekly_profit_trend_title": {"ar": "أرباح الشركة الأسبوعية (آخر توزيعات)", "en": "Company Weekly Profit (recent distributions)", "pt": "Lucro Semanal da Empresa (distribuições recentes)", "tr": "Şirket Haftalık Kârı (son dağıtımlar)", "id": "Laba Mingguan Perusahaan (distribusi terbaru)"},
    "dividend_share_pct_col": {"ar": "نسبة الملكية (ونسبته من صندوق الأرباح)", "en": "Ownership % (= their share of the dividend fund)", "pt": "% de Propriedade (= sua parte no fundo de dividendos)", "tr": "Sahiplik % (= temettü fonundaki payı)", "id": "Kepemilikan % (= bagian dana dividen mereka)"},
    "net_profit_label": {"ar": "صافي الربح الأسبوعي", "en": "Weekly Net Profit", "pt": "Lucro Líquido Semanal", "tr": "Haftalık Net Kâr", "id": "Laba Bersih Mingguan"},
    "distribute_btn": {"ar": "توزيع الأرباح", "en": "Distribute Dividends", "pt": "Distribuir Dividendos", "tr": "Temettüleri Dağıt", "id": "Distribusikan Dividen"},
    "confirm_distribute_dividend": {"ar": "متأكد إنك عايز توزع الأرباح دي؟ الفلوس هتضاف فورًا لرصيد أكبر 5 مساهمين ومفيش تراجع.",
                                      "en": "Are you sure you want to distribute these dividends? The money will be added immediately to the top 5 shareholders' balances and cannot be undone.",
                                      "pt": "Tem certeza de que deseja distribuir esses dividendos? O dinheiro será adicionado imediatamente aos saldos dos 5 maiores acionistas e não pode ser desfeito.",
                                      "tr": "Bu temettüleri dağıtmak istediğinizden emin misiniz? Para hemen en büyük 5 hissedarın bakiyesine eklenecek ve geri alınamaz.",
                                      "id": "Apakah Anda yakin ingin mendistribusikan dividen ini? Uang akan langsung ditambahkan ke saldo 5 pemegang saham teratas dan tidak dapat dibatalkan."},
    "dividend_disabled_hint": {"ar": "نسبة الأرباح للشركة دي = 0% حاليًا (معطّلة). اضبطها من إدارة الأسهم عشان تقدر توزع أرباح.",
                                 "en": "This company's dividend percentage is currently 0% (disabled). Set it from Manage Stocks to be able to distribute dividends.",
                                 "pt": "A porcentagem de dividendos desta empresa está atualmente em 0% (desativada). Defina-a em Gerenciar Ações para poder distribuir dividendos.",
                                 "tr": "Bu şirketin temettü yüzdesi şu anda %0 (devre dışı). Temettü dağıtabilmek için Hisseleri Yönet'ten ayarlayın.",
                                 "id": "Persentase dividen perusahaan ini saat ini 0% (nonaktif). Atur dari Kelola Saham agar dapat mendistribusikan dividen."},
    "dividend_history_title": {"ar": "سجل توزيعات الأرباح", "en": "Dividend History", "pt": "Histórico de Dividendos", "tr": "Temettü Geçmişi", "id": "Riwayat Dividen"},
    "total_fund_label": {"ar": "صندوق الأرباح", "en": "Dividend Fund", "pt": "Fundo de Dividendos", "tr": "Temettü Fonu", "id": "Dana Dividen"},
    "recipients_label": {"ar": "عدد المستفيدين", "en": "Recipients", "pt": "Beneficiários", "tr": "Alıcılar", "id": "Penerima"},
    "dividend_company_note": {"ar": "بتتوزع أسبوعيًا على أكبر 5 مساهمين بالتناسب مع عدد الأسهم.",
                                "en": "Distributed weekly among the top 5 shareholders, proportional to shares owned.",
                                "pt": "Distribuído semanalmente entre os 5 maiores acionistas, proporcional às ações possuídas.",
                                "tr": "Sahip olunan hisseyle orantılı olarak haftalık olarak en büyük 5 hissedar arasında dağıtılır.",
                                "id": "Didistribusikan mingguan di antara 5 pemegang saham teratas, proporsional dengan saham yang dimiliki."},
    "dividend_friday_note": {"ar": "📅 توزيع الأرباح بيتم كل يوم جمعة.", "en": "📅 Dividends are distributed every Friday.", "pt": "📅 Os dividendos são distribuídos toda sexta-feira.", "tr": "📅 Temettüler her Cuma dağıtılır.", "id": "📅 Dividen didistribusikan setiap hari Jumat."},
    "no_dividend_history_yet": {"ar": "لسه مفيش أي توزيعات أرباح.", "en": "No dividend distributions yet.", "pt": "Ainda não há distribuições de dividendos.", "tr": "Henüz temettü dağıtımı yok.", "id": "Belum ada distribusi dividen."},
    "flash_dividend_disabled": {"ar": "نسبة الأرباح للشركة دي معطّلة (0%) - ظبطها الأول", "en": "This company's dividend is disabled (0%) - set it first", "pt": "O dividendo desta empresa está desativado (0%) - defina-o primeiro", "tr": "Bu şirketin temettüsü devre dışı (%0) - önce ayarlayın", "id": "Dividen perusahaan ini nonaktif (0%) - atur dulu"},
    "flash_dividend_distributed": {"ar": "تم توزيع الأرباح بنجاح", "en": "Dividends distributed successfully", "pt": "Dividendos distribuídos com sucesso", "tr": "Temettüler başarıyla dağıtıldı", "id": "Dividen berhasil didistribusikan"},
    "feature_under_update_title": {"ar": "الميزة دي تحت التحديث حاليًا", "en": "This feature is currently under update", "pt": "Este recurso está em atualização no momento", "tr": "Bu özellik şu anda güncelleniyor", "id": "Fitur ini sedang dalam pembaruan"},
    "feature_under_update_body": {"ar": "تسجيل شركات اللاعبين كأسهم متداولة مقفول مؤقتًا. هيرجع تاني قريبًا.",
                                     "en": "Registering player companies as tradable stocks is temporarily closed. It will be back soon.",
                                     "pt": "O registro de empresas de jogadores como ações negociáveis está temporariamente fechado. Voltará em breve.",
                                     "tr": "Oyuncu şirketlerinin işlem gören hisseler olarak kaydedilmesi geçici olarak kapatıldı. Yakında geri dönecek.",
                                     "id": "Pendaftaran perusahaan pemain sebagai saham yang dapat diperdagangkan ditutup sementara. Akan kembali segera."},
    "logout": {"ar": "خروج", "en": "Logout", "pt": "Sair", "tr": "Çıkış Yap", "id": "Keluar"},
    "please_login_message": {"ar": "لازم تسجل دخول الأول عشان تدخل الصفحة دي.",
                              "en": "Please log in to access this page.",
                              "pt": "Faça login para acessar esta página.", "tr": "Bu sayfaya erişmek için giriş yapmalısınız.", "id": "Silakan masuk untuk mengakses halaman ini."},
    "settings": {"ar": "الإعدادات", "en": "Settings", "pt": "Configurações", "tr": "Ayarlar", "id": "Pengaturan"},
    "guide_nav": {"ar": "شرح التطبيق", "en": "App Guide", "pt": "Guia do App", "tr": "Uygulama Rehberi", "id": "Panduan Aplikasi"},
    "guide_title": {"ar": "شرح التطبيق", "en": "App Guide", "pt": "Guia do App", "tr": "Uygulama Rehberi", "id": "Panduan Aplikasi"},
    "guide_lede": {"ar": "كل حاجة تحتاج تعرفها عن GNID BANK في مكان واحد. دوس على أي قسم عشان يتفتح.",
                     "en": "Everything you need to know about GNID BANK in one place. Tap any section to expand it.",
                     "pt": "Tudo o que você precisa saber sobre o GNID BANK em um só lugar. Toque em qualquer seção para expandi-la.",
                     "tr": "GNID BANK hakkında bilmeniz gereken her şey tek bir yerde. Genişletmek için herhangi bir bölüme dokunun.",
                     "id": "Semua yang perlu Anda ketahui tentang GNID BANK di satu tempat. Ketuk bagian mana pun untuk memperluasnya."},
    "guide_section_about_title": {"ar": "🏦 إيه هو GNID BANK؟", "en": "🏦 What is GNID BANK?", "pt": "🏦 O que é o GNID BANK?", "tr": "🏦 GNID BANK nedir?", "id": "🏦 Apa itu GNID BANK?"},
    "guide_section_about_body": {
        "ar": "GNID BANK هو البنك الرسمي داخل لعبة Diplomacia — بتقدر تضيف رصيد، تستثمر، تتداول أسهم، تطلب ديون، وتسحب فلوسك، وكل ده متزامن مع حسابك الحقيقي في اللعبة.",
        "en": "GNID BANK is the official bank inside the Diplomacia game — you can add balance, invest, trade stocks, request loans, and withdraw your money, all synced with your real in-game account.",
        "pt": "O GNID BANK é o banco oficial dentro do jogo Diplomacia — você pode adicionar saldo, investir, negociar ações, solicitar empréstimos e sacar seu dinheiro, tudo sincronizado com sua conta real no jogo.",
        "tr": "GNID BANK, Diplomacia oyunu içindeki resmi bankadır — bakiye ekleyebilir, yatırım yapabilir, hisse senedi alıp satabilir, kredi talep edebilir ve paranızı çekebilirsiniz; hepsi oyun içindeki gerçek hesabınızla senkronize.",
        "id": "GNID BANK adalah bank resmi di dalam game Diplomacia — Anda dapat menambah saldo, berinvestasi, memperdagangkan saham, mengajukan pinjaman, dan menarik uang Anda, semuanya tersinkronisasi dengan akun asli Anda dalam game."},
    "guide_section_account_title": {"ar": "👤 الحساب والتوثيق", "en": "👤 Account & Verification", "pt": "👤 Conta e Verificação", "tr": "👤 Hesap ve Doğrulama", "id": "👤 Akun & Verifikasi"},
    "guide_section_account_body": {
        "ar": "بتسجل بيوزرنيم وباسورد ويوزر تليجرام عام (@) بتاعك. لازم يكون اليوزر ده حقيقي وموجود فعلاً عشان تقدر توثقه بعدين. اليوزرنيم بتاعك مش حساس لحالة الأحرف (Ali = ali = ALI). تقدر توثق حسابك بتليجرام من صفحة الإعدادات — التوثيق مطلوب عشان تقدر تطلب دين. لو مالكش يوزر تليجرام عام أصلاً، هتحتاج تعمل واحد من إعدادات تليجرام نفسه (Settings → Username) قبل ما تقدر توثق.",
        "en": "You register with a username, password, and your public Telegram username (@). It must be real and existing so you can verify it later. Your username isn't case-sensitive (Ali = ali = ALI). You can verify your account via Telegram from the Settings page — verification is required before you can request a loan. If you don't have a public Telegram username, you'll need to set one in Telegram's own Settings → Username first.",
        "pt": "Você se registra com um nome de usuário, senha e seu nome de usuário público do Telegram (@). Ele precisa ser real e existente para que você possa verificá-lo depois. Seu nome de usuário não diferencia maiúsculas de minúsculas (Ali = ali = ALI). Você pode verificar sua conta pelo Telegram na página de Configurações — a verificação é necessária para solicitar um empréstimo. Se você não tiver um nome de usuário público do Telegram, precisará criar um nas próprias Configurações do Telegram (Settings → Username) antes de poder verificar.",
        "tr": "Kullanıcı adı, şifre ve genel Telegram kullanıcı adınızla (@) kayıt olursunuz. Daha sonra doğrulayabilmeniz için bunun gerçek ve mevcut olması gerekir. Kullanıcı adınız büyük/küçük harfe duyarlı değildir (Ali = ali = ALI). Hesabınızı Ayarlar sayfasından Telegram üzerinden doğrulayabilirsiniz — kredi talep edebilmek için doğrulama gereklidir. Genel bir Telegram kullanıcı adınız yoksa, doğrulayabilmeden önce Telegram'ın kendi Ayarlar → Kullanıcı Adı bölümünden bir tane oluşturmanız gerekir.",
        "id": "Anda mendaftar dengan nama pengguna, kata sandi, dan nama pengguna Telegram publik (@) Anda. Nama pengguna Telegram tersebut harus nyata dan ada agar Anda dapat memverifikasinya nanti. Nama pengguna Anda tidak peka huruf besar/kecil (Ali = ali = ALI). Anda dapat memverifikasi akun Anda melalui Telegram dari halaman Pengaturan — verifikasi diperlukan sebelum Anda dapat mengajukan pinjaman. Jika Anda belum memiliki nama pengguna Telegram publik, Anda perlu membuatnya terlebih dahulu di Pengaturan Telegram sendiri (Settings → Username) sebelum dapat memverifikasi."},
    "guide_section_deposit_title": {"ar": "💰 إضافة رصيد", "en": "💰 Add Balance", "pt": "💰 Adicionar Saldo", "tr": "💰 Bakiye Ekle", "id": "💰 Tambah Saldo"},
    "guide_section_deposit_body": {
        "ar": "لإضافة رصيد، بتحول المبلغ لحساب الخزنة داخل اللعبة نفسها، والنظام بيكتشف التحويل تلقائيًا ويضيف الرصيد لحسابك في البنك (المبلغ المرسل بيتضمن آيدي حسابك مشفّر جواه). مفيش تدخل يدوي مطلوب.",
        "en": "To add balance, you transfer the amount to the treasury account inside the game itself, and the system automatically detects the transfer and credits your bank account (the sent amount encodes your account ID within it). No manual step needed.",
        "pt": "Para adicionar saldo, você transfere o valor para a conta do tesouro dentro do próprio jogo, e o sistema detecta automaticamente a transferência e credita sua conta bancária (o valor enviado codifica seu ID de conta dentro dele). Nenhuma etapa manual é necessária.",
        "tr": "Bakiye eklemek için tutarı oyunun kendi içindeki hazine hesabına aktarırsınız ve sistem transferi otomatik olarak algılayıp banka hesabınıza yatırır (gönderilen tutar, hesap kimliğinizi içinde kodlar). Herhangi bir manuel adım gerekmez.",
        "id": "Untuk menambah saldo, Anda mentransfer jumlah tersebut ke akun kas di dalam game itu sendiri, dan sistem secara otomatis mendeteksi transfer tersebut dan mengkredit akun bank Anda (jumlah yang dikirim menyandikan ID akun Anda di dalamnya). Tidak diperlukan langkah manual."},
    "guide_section_market_title": {"ar": "📈 الأسهم", "en": "📈 Stocks", "pt": "📈 Ações", "tr": "📈 Hisseler", "id": "📈 Saham"},
    "guide_section_market_body": {
        "ar": "فيه طريقتين للشراء: (1) الطرح الرسمي (IPO) — شراء مباشر من البنك بسعر ثابت وبلا أي عمولة. (2) التداول بين الأفراد — بتحط أمر بيع أو شراء بسعرك انت، والنظام بيقابله تلقائي مع أمر مناسب من مستخدم تاني؛ وده عليه عمولة 2.5% على المشتري لصالح خزينة GNID. السعر المعروض لأي سهم هو سعر آخر صفقة حصلت عليه فعليًا. تقدر تشوف كل صفقاتك في قسم \"سجل صفقاتي\"، وتفلتر الأوامر المفتوحة (الكل/شراء/بيع)، وتشوف كام سهم يملك أي حد قدّم أمر بيع قبل ما توافق.",
        "en": "There are two ways to buy: (1) Official Offering (IPO) — direct purchase from the bank at a fixed price with no fee. (2) Peer-to-peer trading — you place a buy or sell order at your own price, and the system automatically matches it with a suitable order from another user; this carries a 2.5% fee on the buyer for the GNID treasury. The displayed price for any stock is the price of its last actual trade. You can see all your trades in \"My Trades\", filter open orders (All/Buy/Sell), and see how many shares a seller actually owns before trading with them.",
        "pt": "Há duas formas de comprar: (1) Oferta Oficial (IPO) — compra direta do banco a um preço fixo e sem taxa. (2) Negociação entre usuários — você coloca uma ordem de compra ou venda no seu próprio preço, e o sistema a combina automaticamente com uma ordem adequada de outro usuário; isso tem uma taxa de 2,5% sobre o comprador para o tesouro da GNID. O preço exibido de qualquer ação é o preço da sua última negociação real. Você pode ver todas as suas negociações em \"Minhas Negociações\", filtrar as ordens abertas (Todas/Compra/Venda) e ver quantas ações um vendedor realmente possui antes de negociar com ele.",
        "tr": "İki satın alma yöntemi vardır: (1) Resmi Arz (IPO) — bankadan sabit bir fiyattan ve ücretsiz doğrudan satın alma. (2) Kullanıcılar arası işlem — kendi fiyatınızdan bir alım veya satım emri verirsiniz ve sistem bunu otomatik olarak başka bir kullanıcının uygun emriyle eşleştirir; bu, GNID hazinesi için alıcıdan %2,5 ücret alır. Herhangi bir hissenin gösterilen fiyatı, gerçekleşen son işleminin fiyatıdır. Tüm işlemlerinizi \"İşlemlerim\" bölümünde görebilir, açık emirleri filtreleyebilir (Tümü/Alım/Satım) ve bir satıcıyla işlem yapmadan önce gerçekte kaç hisseye sahip olduğunu görebilirsiniz.",
        "id": "Ada dua cara untuk membeli: (1) Penawaran Resmi (IPO) — pembelian langsung dari bank dengan harga tetap tanpa biaya. (2) Perdagangan antarpengguna — Anda memasang order beli atau jual dengan harga Anda sendiri, dan sistem secara otomatis mencocokkannya dengan order yang sesuai dari pengguna lain; ini dikenakan biaya 2,5% pada pembeli untuk kas GNID. Harga yang ditampilkan untuk saham mana pun adalah harga transaksi terakhirnya yang sebenarnya. Anda dapat melihat semua transaksi Anda di \"Transaksi Saya\", memfilter order terbuka (Semua/Beli/Jual), dan melihat berapa banyak saham yang benar-benar dimiliki penjual sebelum bertransaksi dengannya."},
    "guide_section_invest_title": {"ar": "🏦 الاستثمار", "en": "🏦 Investment", "pt": "🏦 Investimento", "tr": "🏦 Yatırım", "id": "🏦 Investasi"},
    "guide_section_invest_body": {
        "ar": "فيه خطتين ثابتتين: 7 أيام بعائد +5%، و14 يوم بعائد +11%. تختار الخطة وقت ما تستثمر، ومبلغك بيتجمّد لمدة الخطة، وبعد ما تستحق بيترجعلك تلقائي (المبلغ الأصلي + العائد) على رصيدك من غير أي تدخل منك.",
        "en": "There are two fixed plans: 7 days at +5% return, and 14 days at +11% return. You pick the plan when you invest, your amount is locked for that term, and once it matures it's automatically returned to your balance (principal + return) with no action needed from you.",
        "pt": "Existem dois planos fixos: 7 dias com retorno de +5% e 14 dias com retorno de +11%. Você escolhe o plano ao investir, seu valor fica bloqueado durante esse prazo, e assim que vence, ele é devolvido automaticamente ao seu saldo (valor principal + retorno) sem nenhuma ação necessária da sua parte.",
        "tr": "İki sabit plan vardır: %5 getirili 7 gün ve %11 getirili 14 gün. Yatırım yaparken planı seçersiniz, tutarınız o süre boyunca kilitlenir ve vadesi dolduğunda hiçbir işlem yapmanıza gerek kalmadan otomatik olarak bakiyenize (anapara + getiri) geri döner.",
        "id": "Ada dua paket tetap: 7 hari dengan imbal hasil +5%, dan 14 hari dengan imbal hasil +11%. Anda memilih paket saat berinvestasi, jumlah Anda dikunci selama jangka waktu tersebut, dan setelah jatuh tempo akan otomatis dikembalikan ke saldo Anda (pokok + imbal hasil) tanpa tindakan apa pun dari Anda."},
    "guide_section_loans_title": {"ar": "🤝 الديون", "en": "🤝 Loans", "pt": "🤝 Empréstimos", "tr": "🤝 Krediler", "id": "🤝 Pinjaman"},
    "guide_section_loans_body": {
        "ar": "تقدر تطلب دين لو حسابك موثّق بتليجرام. المدد المتاحة: 3 أيام (+5%)، 5 أيام (+10%)، 7 أيام (+20%). لازم موافقة الأدمن/المشرف الأول. لما يوافق، بيتحدد ميعاد استحقاق، وقبله بيوم واحد بتوصلك رسالة تليجرام تذكّرك. لو فات الميعاد: لو معاك رصيد كفاية، المبلغ بيتسحب تلقائي ويتسدد الدين. لو رصيدك مش كفاية، حسابك بيتجمد (تتمنع من السحب والتداول وطلب دين جديد) لحد ما تسدد أو يبقى معاك رصيد كفاية — وقتها بيتفك التجميد تلقائي. وفوق كل ده، لو ماسددتش الدين خلال المدة، بيتم نشر اسمك كمحتال، وطردك من الجروبات، ومعادش هيتم التعامل معاك تاني نهائي.",
        "en": "You can request a loan if your account is Telegram-verified. Available terms: 3 days (+5%), 5 days (+10%), 7 days (+20%). It needs admin/mod approval first. Once approved, a due date is set, and 1 day before it you get a Telegram reminder. If you miss the deadline: if you have enough balance, the amount is auto-deducted and the loan is settled. If your balance isn't enough, your account is frozen (blocked from withdrawing, trading, and requesting new loans) until you repay or have enough balance — at which point the freeze lifts automatically. On top of that, if you don't repay within the term, you'll be publicly called out as a scammer, kicked from the groups, and never dealt with again.",
        "pt": "Você pode solicitar um empréstimo se sua conta estiver verificada pelo Telegram. Prazos disponíveis: 3 dias (+5%), 5 dias (+10%), 7 dias (+20%). É necessária a aprovação de um admin/moderador primeiro. Após a aprovação, uma data de vencimento é definida, e 1 dia antes você recebe um lembrete pelo Telegram. Se você perder o prazo: se tiver saldo suficiente, o valor é deduzido automaticamente e o empréstimo é quitado. Se seu saldo não for suficiente, sua conta é congelada (bloqueada para saques, negociações e novos empréstimos) até você pagar ou ter saldo suficiente — momento em que o congelamento é removido automaticamente. Além disso, se você não pagar dentro do prazo, seu nome será divulgado publicamente como golpista, você será removido dos grupos e nunca mais será atendido.",
        "tr": "Hesabınız Telegram ile doğrulanmışsa kredi talep edebilirsiniz. Mevcut vadeler: 3 gün (+%5), 5 gün (+%10), 7 gün (+%20). Önce admin/moderatör onayı gerekir. Onaylandığında bir vade tarihi belirlenir ve bundan 1 gün önce Telegram hatırlatması alırsınız. Süreyi kaçırırsanız: yeterli bakiyeniz varsa tutar otomatik olarak düşülür ve kredi kapatılır. Bakiyeniz yeterli değilse, ödeme yapana veya bakiyeniz yeterli olana kadar hesabınız dondurulur (para çekme, işlem yapma ve yeni kredi talep etmekten men edilirsiniz) — bu noktada dondurma otomatik olarak kaldırılır. Bunun da ötesinde, süresi içinde ödemezseniz, adınız dolandırıcı olarak ilan edilir, gruplardan atılırsınız ve bir daha asla sizinle iş yapılmaz.",
        "id": "Anda dapat mengajukan pinjaman jika akun Anda telah diverifikasi Telegram. Jangka waktu yang tersedia: 3 hari (+5%), 5 hari (+10%), 7 hari (+20%). Ini memerlukan persetujuan admin/mod terlebih dahulu. Setelah disetujui, tanggal jatuh tempo ditetapkan, dan 1 hari sebelumnya Anda mendapat pengingat Telegram. Jika Anda melewatkan tenggat waktu: jika saldo Anda cukup, jumlahnya akan otomatis dipotong dan pinjaman lunas. Jika saldo Anda tidak cukup, akun Anda dibekukan (diblokir dari menarik, berdagang, dan mengajukan pinjaman baru) hingga Anda membayar atau saldo Anda cukup — saat itu pembekuan akan otomatis dicabut. Selain itu, jika Anda tidak membayar dalam jangka waktu tersebut, nama Anda akan diumumkan sebagai penipu, dikeluarkan dari grup, dan tidak akan pernah dilayani lagi."},
    "guide_section_withdraw_title": {"ar": "💸 السحب", "en": "💸 Withdraw", "pt": "💸 Saque", "tr": "💸 Para Çekme", "id": "💸 Penarikan"},
    "guide_section_withdraw_body": {
        "ar": "بتطلب سحب برابط حسابك داخل اللعبة (لازم يكون بالشكل: https://diplomacia.com.tr/profile/player/رقم) والمبلغ المطلوب. المبلغ بيتخصم من رصيدك فورًا وقت الطلب. الأدمن بيحوّل يدوي أو تلقائي (Auto-Send) ويقفل الطلب. تقدر تلغي طلبك بنفسك طالما لسه \"قيد الانتظار\" والمبلغ بيرجعلك فورًا.",
        "en": "You request a withdrawal with your in-game account link (must be in the format: https://diplomacia.com.tr/profile/player/number) and the amount. The amount is deducted from your balance immediately upon request. The admin transfers it manually or automatically (Auto-Send) and closes the request. You can cancel your own request yourself as long as it's still \"pending\" and the amount is returned to you immediately.",
        "pt": "Você solicita um saque com o link da sua conta no jogo (deve estar no formato: https://diplomacia.com.tr/profile/player/número) e o valor. O valor é deduzido do seu saldo imediatamente após a solicitação. O admin transfere manualmente ou automaticamente (Auto-Send) e fecha a solicitação. Você pode cancelar sua própria solicitação enquanto ela ainda estiver \"pendente\", e o valor é devolvido a você imediatamente.",
        "tr": "Oyun içi hesap bağlantınızla (şu formatta olmalı: https://diplomacia.com.tr/profile/player/numara) ve tutarla bir para çekme talebi oluşturursunuz. Tutar, talep anında bakiyenizden hemen düşülür. Admin bunu manuel veya otomatik (Auto-Send) olarak aktarır ve talebi kapatır. Talebiniz hâlâ \"beklemede\" olduğu sürece kendiniz iptal edebilirsiniz ve tutar hemen size iade edilir.",
        "id": "Anda mengajukan penarikan dengan tautan akun dalam game Anda (harus dalam format: https://diplomacia.com.tr/profile/player/nomor) dan jumlahnya. Jumlah tersebut langsung dipotong dari saldo Anda saat pengajuan. Admin mentransfernya secara manual atau otomatis (Auto-Send) dan menutup permintaan tersebut. Anda dapat membatalkan permintaan Anda sendiri selama masih \"menunggu\" dan jumlahnya akan langsung dikembalikan kepada Anda."},
    "guide_section_settings_title": {"ar": "🔧 الإعدادات", "en": "🔧 Settings", "pt": "🔧 Configurações", "tr": "🔧 Ayarlar", "id": "🔧 Pengaturan"},
    "guide_section_settings_body": {
        "ar": "من هنا تقدر: تغيير كلمة السر، تغيير اليوزرنيم (مرة واحدة بس)، تغيير يوزر التليجرام، وتوثيق حسابك بالبوت.",
        "en": "From here you can: change your password, change your username (one time only), change your Telegram username, and verify your account via the bot.",
        "pt": "A partir daqui você pode: alterar sua senha, alterar seu nome de usuário (apenas uma vez), alterar seu nome de usuário do Telegram e verificar sua conta pelo bot.",
        "tr": "Buradan şunları yapabilirsiniz: şifrenizi değiştirme, kullanıcı adınızı değiştirme (yalnızca bir kez), Telegram kullanıcı adınızı değiştirme ve botla hesabınızı doğrulama.",
        "id": "Dari sini Anda dapat: mengubah kata sandi, mengubah nama pengguna (hanya sekali), mengubah nama pengguna Telegram, dan memverifikasi akun Anda melalui bot."},
    "guide_section_frozen_title": {"ar": "🔒 تجميد الحساب", "en": "🔒 Account Freezing", "pt": "🔒 Congelamento de Conta", "tr": "🔒 Hesap Dondurma", "id": "🔒 Pembekuan Akun"},
    "guide_section_frozen_body": {
        "ar": "حسابك بيتجمد لو فات ميعاد سداد دين ورصيدك مش كفاية. وانت مجمّد، مش هتقدر تسحب، تتداول، أو تطلب دين جديد. التجميد بيتفك تلقائي أول ما تسدد الدين (يدوي أو تلقائي لما يبقى معاك رصيد كفاية).",
        "en": "Your account gets frozen if a loan's due date passes and your balance isn't enough. While frozen, you can't withdraw, trade, or request a new loan. The freeze lifts automatically as soon as the loan is repaid (manually, or automatically once your balance is enough).",
        "pt": "Sua conta é congelada se o prazo de um empréstimo vencer e seu saldo não for suficiente. Enquanto estiver congelada, você não pode sacar, negociar ou solicitar um novo empréstimo. O congelamento é removido automaticamente assim que o empréstimo é pago (manualmente, ou automaticamente quando seu saldo for suficiente).",
        "tr": "Bir kredinin vade tarihi geçer ve bakiyeniz yeterli değilse hesabınız dondurulur. Donduruldukça para çekemez, işlem yapamaz veya yeni kredi talep edemezsiniz. Kredi ödendiğinde (manuel olarak veya bakiyeniz yeterli olduğunda otomatik olarak) dondurma otomatik olarak kaldırılır.",
        "id": "Akun Anda akan dibekukan jika tanggal jatuh tempo pinjaman terlewati dan saldo Anda tidak cukup. Saat dibekukan, Anda tidak dapat menarik, berdagang, atau mengajukan pinjaman baru. Pembekuan akan otomatis dicabut segera setelah pinjaman dilunasi (secara manual, atau otomatis begitu saldo Anda cukup)."},
    "contact_support_title": {"ar": "التواصل مع الدعم", "en": "Contact Support", "pt": "Contatar Suporte", "tr": "Destekle İletişime Geç", "id": "Hubungi Dukungan"},
    "contact_support_lede": {"ar": "عندك مشكلة أو سؤال؟ انضم لجروب البنك على تليجرام وهيتم الرد عليك.",
                               "en": "Have an issue or a question? Join the bank's Telegram group and you'll get a response.",
                               "pt": "Tem um problema ou uma pergunta? Entre no grupo do banco no Telegram e você receberá uma resposta.",
                               "tr": "Bir sorununuz veya sorunuz mu var? Bankanın Telegram grubuna katılın, size yanıt verilecektir.",
                               "id": "Punya masalah atau pertanyaan? Bergabunglah dengan grup Telegram bank dan Anda akan mendapat tanggapan."},
    "contact_support_btn": {"ar": "جروب البنك على تليجرام", "en": "Bank's Telegram Group", "pt": "Grupo do Banco no Telegram", "tr": "Bankanın Telegram Grubu", "id": "Grup Telegram Bank"},
    "settings_title": {"ar": "إعدادات الحساب", "en": "Account Settings", "pt": "Configurações da Conta", "tr": "Hesap Ayarları", "id": "Pengaturan Akun"},
    "change_password_section": {"ar": "تغيير كلمة السر", "en": "Change Password", "pt": "Alterar Senha", "tr": "Şifre Değiştir", "id": "Ubah Kata Sandi"},
    "current_password_label": {"ar": "كلمة السر الحالية", "en": "Current Password", "pt": "Senha Atual", "tr": "Mevcut Şifre", "id": "Kata Sandi Saat Ini"},
    "new_password_label": {"ar": "كلمة السر الجديدة", "en": "New Password", "pt": "Nova Senha", "tr": "Yeni Şifre", "id": "Kata Sandi Baru"},
    "confirm_new_password_label": {"ar": "أكد كلمة السر الجديدة", "en": "Confirm New Password", "pt": "Confirme a Nova Senha", "tr": "Yeni Şifreyi Onayla", "id": "Konfirmasi Kata Sandi Baru"},
    "confirm_password_label": {"ar": "أكد كلمة السر", "en": "Confirm Password", "pt": "Confirme a Senha", "tr": "Şifreyi Onayla", "id": "Konfirmasi Kata Sandi"},
    "change_telegram_section": {"ar": "تغيير يوزر التليجرام", "en": "Change Telegram Username", "pt": "Alterar Usuário do Telegram", "tr": "Telegram Kullanıcı Adını Değiştir", "id": "Ubah Nama Pengguna Telegram"},
    "telegram_username_label": {"ar": "يوزر التليجرام الجديد", "en": "New Telegram Username", "pt": "Novo Usuário do Telegram", "tr": "Yeni Telegram Kullanıcı Adı", "id": "Nama Pengguna Telegram Baru"},
    "save_password_settings_btn": {"ar": "حفظ كلمة السر", "en": "Save Password", "pt": "Salvar Senha", "tr": "Şifreyi Kaydet", "id": "Simpan Kata Sandi"},
    "save_telegram_btn": {"ar": "حفظ اليوزر", "en": "Save Username", "pt": "Salvar Usuário", "tr": "Kullanıcı Adını Kaydet", "id": "Simpan Nama Pengguna"},
    "flash_wrong_current_password": {"ar": "كلمة السر الحالية غلط", "en": "Current password is incorrect", "pt": "A senha atual está incorreta", "tr": "Mevcut şifre yanlış", "id": "Kata sandi saat ini salah"},
    "flash_passwords_dont_match": {"ar": "كلمة السر الجديدة والتأكيد مش متطابقين", "en": "New password and confirmation don't match", "pt": "A nova senha e a confirmação não coincidem", "tr": "Yeni şifre ve onayı eşleşmiyor", "id": "Kata sandi baru dan konfirmasi tidak cocok"},
    "flash_password_too_short": {"ar": "كلمة السر لازم تكون 6 حروف/أرقام على الأقل", "en": "Password must be at least 6 characters", "pt": "A senha deve ter pelo menos 6 caracteres", "tr": "Şifre en az 6 karakter olmalı", "id": "Kata sandi harus minimal 6 karakter"},
    "flash_password_changed_self": {"ar": "تم تغيير كلمة السر بنجاح", "en": "Password changed successfully", "pt": "Senha alterada com sucesso", "tr": "Şifre başarıyla değiştirildi", "id": "Kata sandi berhasil diubah"},
    "flash_telegram_updated": {"ar": "تم تحديث يوزر التليجرام", "en": "Telegram username updated", "pt": "Usuário do Telegram atualizado", "tr": "Telegram kullanıcı adı güncellendi", "id": "Nama pengguna Telegram diperbarui"},
    "flash_telegram_locked": {"ar": "حسابك موثّق، مش تقدر تغيّر يوزر التليجرام يدويًا. لو عايز تغيّره، وثّق تاني بحساب تليجرام تاني وهيتحدث تلقائي.",
                                "en": "Your account is verified, so you can't manually change your Telegram username. To change it, verify again with a different Telegram account and it'll update automatically.",
                                "pt": "Sua conta está verificada, então você não pode alterar manualmente seu nome de usuário do Telegram. Para alterá-lo, verifique novamente com uma conta diferente do Telegram e ele será atualizado automaticamente.",
                                "tr": "Hesabınız doğrulandı, bu yüzden Telegram kullanıcı adınızı manuel olarak değiştiremezsiniz. Değiştirmek için farklı bir Telegram hesabıyla tekrar doğrulayın, otomatik olarak güncellenecektir.",
                                "id": "Akun Anda terverifikasi, jadi Anda tidak dapat mengubah nama pengguna Telegram secara manual. Untuk mengubahnya, verifikasi lagi dengan akun Telegram yang berbeda dan itu akan diperbarui secara otomatis."},
    "telegram_locked_note": {"ar": "حسابك موثّق ✅ — اليوزر ده مقفول ومطابق لحسابك الحقيقي في تليجرام.",
                               "en": "Your account is verified ✅ — this username is locked and matches your real Telegram account.",
                               "pt": "Sua conta está verificada ✅ — este nome de usuário está bloqueado e corresponde à sua conta real do Telegram.",
                               "tr": "Hesabınız doğrulandı ✅ — bu kullanıcı adı kilitli ve gerçek Telegram hesabınızla eşleşiyor.",
                               "id": "Akun Anda terverifikasi ✅ — nama pengguna ini terkunci dan cocok dengan akun Telegram asli Anda."},
    "change_account_username_section": {"ar": "تغيير اسم المستخدم (يوزر الحساب)", "en": "Change Account Username", "pt": "Alterar Nome de Usuário da Conta", "tr": "Hesap Kullanıcı Adını Değiştir", "id": "Ubah Nama Pengguna Akun"},
    "change_account_username_lede": {"ar": "تقدر تغيّر يوزر حسابك في البنك مرة واحدة بس — خد بالك واختار كويس قبل ما تحفظ.",
                                       "en": "You can change your bank account username only once — choose carefully before saving.",
                                       "pt": "Você pode alterar o nome de usuário da sua conta bancária apenas uma vez — escolha com cuidado antes de salvar.",
                                       "tr": "Banka hesap kullanıcı adınızı yalnızca bir kez değiştirebilirsiniz — kaydetmeden önce dikkatli seçin.",
                                       "id": "Anda hanya dapat mengubah nama pengguna akun bank Anda satu kali — pilih dengan hati-hati sebelum menyimpan."},
    "new_account_username_label": {"ar": "اسم المستخدم الجديد", "en": "New Username", "pt": "Novo Nome de Usuário", "tr": "Yeni Kullanıcı Adı", "id": "Nama Pengguna Baru"},
    "save_account_username_btn": {"ar": "احفظ اليوزر الجديد", "en": "Save New Username", "pt": "Salvar Novo Nome de Usuário", "tr": "Yeni Kullanıcı Adını Kaydet", "id": "Simpan Nama Pengguna Baru"},
    "account_username_locked_note": {"ar": "استخدمت فرصة تغيير اليوزر بالفعل. اليوزر الحالي:", "en": "You've already used your one-time username change. Current username:", "pt": "Você já usou sua alteração única de nome de usuário. Nome de usuário atual:", "tr": "Tek seferlik kullanıcı adı değişikliğinizi zaten kullandınız. Mevcut kullanıcı adı:", "id": "Anda sudah menggunakan perubahan nama pengguna satu kali Anda. Nama pengguna saat ini:"},
    "flash_username_empty": {"ar": "لازم تكتب يوزر", "en": "You must enter a username", "pt": "Você deve inserir um nome de usuário", "tr": "Bir kullanıcı adı girmelisiniz", "id": "Anda harus memasukkan nama pengguna"},
    "flash_username_taken": {"ar": "اليوزر ده متسجل بالفعل، اختار غيره", "en": "That username is already taken, choose another", "pt": "Esse nome de usuário já está em uso, escolha outro", "tr": "Bu kullanıcı adı zaten alınmış, başka bir tane seçin", "id": "Nama pengguna itu sudah digunakan, pilih yang lain"},
    "flash_username_already_used": {"ar": "استخدمت فرصة تغيير اليوزر بالفعل، مش هتقدر تغيّره تاني", "en": "You've already used your one-time username change, you can't change it again", "pt": "Você já usou sua alteração única de nome de usuário, não pode alterá-lo novamente", "tr": "Tek seferlik kullanıcı adı değişikliğinizi zaten kullandınız, tekrar değiştiremezsiniz", "id": "Anda sudah menggunakan perubahan nama pengguna satu kali Anda, tidak dapat mengubahnya lagi"},
    "flash_username_locked_verified": {"ar": "حسابك موثّق بتليجرام، مش ممكن تغيّر اليوزر بعد التوثيق", "en": "Your account is Telegram-verified, you can't change your username after verification", "pt": "Sua conta está verificada pelo Telegram, você não pode alterar seu nome de usuário após a verificação", "tr": "Hesabınız Telegram ile doğrulandı, doğrulamadan sonra kullanıcı adınızı değiştiremezsiniz", "id": "Akun Anda telah diverifikasi Telegram, Anda tidak dapat mengubah nama pengguna setelah verifikasi"},
    "account_username_locked_verified_note": {"ar": "حسابك موثّق بتليجرام فمش ممكن تغيّر اليوزر تاني. اليوزر الحالي:", "en": "Your account is Telegram-verified, so your username can't be changed anymore. Current username:", "pt": "Sua conta está verificada pelo Telegram, então seu nome de usuário não pode mais ser alterado. Nome de usuário atual:", "tr": "Hesabınız Telegram ile doğrulandı, bu yüzden kullanıcı adınız artık değiştirilemez. Mevcut kullanıcı adı:", "id": "Akun Anda telah diverifikasi Telegram, jadi nama pengguna Anda tidak dapat diubah lagi. Nama pengguna saat ini:"},
    "flash_username_changed": {"ar": "تم تغيير اليوزر بنجاح", "en": "Username changed successfully", "pt": "Nome de usuário alterado com sucesso", "tr": "Kullanıcı adı başarıyla değiştirildi", "id": "Nama pengguna berhasil diubah"},

    "telegram_verify_title": {"ar": "توثيق الحساب عن طريق بوت تليجرام", "en": "Verify Your Account via Telegram Bot", "pt": "Verifique sua Conta pelo Bot do Telegram", "tr": "Telegram Botu ile Hesabınızı Doğrulayın", "id": "Verifikasi Akun Anda melalui Bot Telegram"},
    "telegram_verify_lede": {"ar": "وثّق حسابك عشان يبقى موثوق أكتر — دوس الزرار، وابعت للبوت، وهيتوثق حسابك تلقائي في ثانية.",
                               "en": "Verify your account to make it more trustworthy — click the button, message the bot, and your account gets verified automatically in seconds.",
                               "pt": "Verifique sua conta para torná-la mais confiável — clique no botão, envie uma mensagem ao bot, e sua conta será verificada automaticamente em segundos.",
                               "tr": "Hesabınızı daha güvenilir kılmak için doğrulayın — butona tıklayın, bota mesaj gönderin, hesabınız saniyeler içinde otomatik olarak doğrulanır.",
                               "id": "Verifikasi akun Anda agar lebih terpercaya — klik tombol, kirim pesan ke bot, dan akun Anda akan terverifikasi otomatis dalam hitungan detik."},
    "telegram_verify_status_verified": {"ar": "موثّق ✅", "en": "Verified ✅", "pt": "Verificado ✅", "tr": "Doğrulandı ✅", "id": "Terverifikasi ✅"},
    "telegram_verify_status_not_verified": {"ar": "مش موثّق", "en": "Not verified", "pt": "Não verificado", "tr": "Doğrulanmadı", "id": "Belum terverifikasi"},
    "telegram_verify_generate_btn": {"ar": "إنشاء كود توثيق", "en": "Generate Verification Code", "pt": "Gerar Código de Verificação", "tr": "Doğrulama Kodu Oluştur", "id": "Buat Kode Verifikasi"},
    "telegram_verify_code_label": {"ar": "الكود بتاعك", "en": "Your code", "pt": "Seu código", "tr": "Kodunuz", "id": "Kode Anda"},
    "telegram_verify_open_bot_btn": {"ar": "افتح البوت وابعت الكود", "en": "Open Bot & Send Code", "pt": "Abrir Bot e Enviar Código", "tr": "Botu Aç ve Kodu Gönder", "id": "Buka Bot & Kirim Kode"},
    "telegram_bot_not_configured": {"ar": "البوت لسه متظبطش من الأدمن، جرب تاني بعدين.", "en": "The bot isn't set up by the admin yet — try again later.", "pt": "O bot ainda não foi configurado pelo admin — tente novamente mais tarde.", "tr": "Bot henüz yönetici tarafından ayarlanmadı — daha sonra tekrar deneyin.", "id": "Bot belum diatur oleh admin — coba lagi nanti."},
    "admin_telegram_setup_title": {"ar": "إعداد بوت التوثيق (Webhook)", "en": "Bot Verification Setup (Webhook)", "pt": "Configuração do Bot de Verificação (Webhook)", "tr": "Doğrulama Botu Kurulumu (Webhook)", "id": "Pengaturan Bot Verifikasi (Webhook)"},
    "admin_telegram_setup_lede": {"ar": "دوس مرة واحدة بعد ما تحط توكن البوت في متغيرات البيئة، عشان تربط البوت بالموقع.",
                                    "en": "Click once after setting the bot token in environment variables, to connect the bot to the site.",
                                    "pt": "Clique uma vez depois de definir o token do bot nas variáveis de ambiente, para conectar o bot ao site.",
                                    "tr": "Botu siteye bağlamak için, bot tokenini ortam değişkenlerine ekledikten sonra bir kez tıklayın.",
                                    "id": "Klik sekali setelah mengatur token bot di environment variables, untuk menghubungkan bot ke situs."},
    "admin_telegram_setup_btn": {"ar": "فعّل البوت", "en": "Activate Bot", "pt": "Ativar Bot", "tr": "Botu Etkinleştir", "id": "Aktifkan Bot"},
    "admin_backup_title": {"ar": "نسخة احتياطية كاملة للبيانات", "en": "Full Data Backup", "pt": "Backup Completo de Dados", "tr": "Tam Veri Yedeği", "id": "Cadangan Data Lengkap"},
    "admin_backup_lede": {"ar": "لو حصل فقدان بيانات، الملف ده بيحتوي على كل المستخدمين (الرصيد، يوزر التليجرام)، كل الاستثمارات، الأسهم المملوكة، طلبات الديون والسحب، وسجل الخزينة - كملف JSON تقدر تحتفظ بيه.",
                           "en": "In case of data loss, this file contains every user (balance, Telegram username), all investments, stock holdings, loan and withdrawal requests, and the treasury log - as a JSON file you can keep safe.",
                           "pt": "Em caso de perda de dados, este arquivo contém todos os usuários (saldo, nome de usuário do Telegram), todos os investimentos, ações possuídas, solicitações de empréstimo e saque, e o registro do tesouro - como um arquivo JSON que você pode guardar.",
                           "tr": "Veri kaybı durumunda, bu dosya tüm kullanıcıları (bakiye, Telegram kullanıcı adı), tüm yatırımları, sahip olunan hisseleri, kredi ve para çekme taleplerini ve hazine günlüğünü içerir - saklayabileceğiniz bir JSON dosyası olarak.",
                           "id": "Jika terjadi kehilangan data, file ini berisi setiap pengguna (saldo, nama pengguna Telegram), semua investasi, saham yang dimiliki, permintaan pinjaman dan penarikan, serta log kas - sebagai file JSON yang dapat Anda simpan dengan aman."},
    "admin_backup_btn": {"ar": "تنزيل النسخة الاحتياطية (JSON)", "en": "Download Backup (JSON)", "pt": "Baixar Backup (JSON)", "tr": "Yedeği İndir (JSON)", "id": "Unduh Cadangan (JSON)"},
    "please_wait": {"ar": "لحظة...", "en": "Please wait...", "pt": "Aguarde...", "tr": "Lütfen bekleyin...", "id": "Mohon tunggu..."},
    "flash_telegram_token_missing": {"ar": "لازم تحط TELEGRAM_BOT_TOKEN في متغيرات البيئة الأول", "en": "You must set TELEGRAM_BOT_TOKEN in environment variables first", "pt": "Você deve definir TELEGRAM_BOT_TOKEN nas variáveis de ambiente primeiro", "tr": "Önce ortam değişkenlerine TELEGRAM_BOT_TOKEN eklemelisiniz", "id": "Anda harus mengatur TELEGRAM_BOT_TOKEN di environment variables terlebih dahulu"},
    "flash_telegram_webhook_set": {"ar": "تم تفعيل البوت بنجاح", "en": "Bot activated successfully", "pt": "Bot ativado com sucesso", "tr": "Bot başarıyla etkinleştirildi", "id": "Bot berhasil diaktifkan"},
    "flash_telegram_webhook_failed": {"ar": "فشل تفعيل البوت", "en": "Failed to activate bot", "pt": "Falha ao ativar o bot", "tr": "Bot etkinleştirilemedi", "id": "Gagal mengaktifkan bot"},
    "telegram_bot_welcome_msg": {"ar": "أهلًا بيك في بوت GNID BANK! روح لصفحة الإعدادات في الموقع واعمل \"إنشاء كود توثيق\"، وابعتلي الكود هنا عشان أوثق حسابك. بعد التوثيق اكتب /menu عشان تشوف كل الخيارات المتاحة.",
                                   "en": "Welcome to the GNID BANK bot! Go to Settings on the site and click \"Generate Verification Code\", then send me that code here to verify your account. Once verified, send /menu to see all available options.",
                                   "pt": "Bem-vindo ao bot do GNID BANK! Vá até Configurações no site e clique em \"Gerar Código de Verificação\", depois me envie esse código aqui para verificar sua conta. Depois de verificado, envie /menu para ver todas as opções disponíveis.",
                                   "tr": "GNID BANK botuna hoş geldiniz! Sitede Ayarlar'a gidin ve \"Doğrulama Kodu Oluştur\"a tıklayın, ardından hesabınızı doğrulamak için bu kodu bana buradan gönderin. Doğrulandıktan sonra tüm seçenekleri görmek için /menu gönderin.",
                                   "id": "Selamat datang di bot GNID BANK! Buka Pengaturan di situs dan klik \"Buat Kode Verifikasi\", lalu kirimkan kode itu ke saya di sini untuk memverifikasi akun Anda. Setelah terverifikasi, kirim /menu untuk melihat semua opsi yang tersedia."},
    "telegram_bot_invalid_code": {"ar": "الكود ده مش صح أو منتهي. روح صفحة الإعدادات واعمل كود جديد.", "en": "That code is invalid or expired. Go to Settings and generate a new one.", "pt": "Esse código é inválido ou expirou. Vá até Configurações e gere um novo.", "tr": "Bu kod geçersiz veya süresi dolmuş. Ayarlar'a gidin ve yeni bir tane oluşturun.", "id": "Kode itu tidak valid atau kedaluwarsa. Buka Pengaturan dan buat kode baru."},
    "telegram_bot_already_linked": {"ar": "الحساب بتاع تليجرام ده متوثق بالفعل بحساب بنكي تاني.", "en": "This Telegram account is already linked to a different bank account.", "pt": "Esta conta do Telegram já está vinculada a outra conta bancária.", "tr": "Bu Telegram hesabı zaten başka bir banka hesabına bağlı.", "id": "Akun Telegram ini sudah tertaut dengan akun bank lain."},
    "telegram_bot_verified_msg": {"ar": "تم توثيق حسابك بنجاح يا {username}! ✅ ابعت /menu دلوقتي عشان تشوف رصيدك وكل الخيارات المتاحة.",
                                    "en": "Your account has been verified, {username}! ✅ Send /menu now to see your balance and all available options.",
                                    "pt": "Sua conta foi verificada, {username}! ✅ Envie /menu agora para ver seu saldo e todas as opções disponíveis.",
                                    "tr": "Hesabınız doğrulandı, {username}! ✅ Bakiyenizi ve tüm seçenekleri görmek için şimdi /menu gönderin.",
                                    "id": "Akun Anda telah diverifikasi, {username}! ✅ Kirim /menu sekarang untuk melihat saldo Anda dan semua opsi yang tersedia."},
    "telegram_bot_need_username_first": {"ar": "لسه معملتش يوزر تليجرام عام (@) — لازم تعمل واحد الأول عشان تقدر توثّق حسابك. روح Settings → Username في تليجرام واعمل يوزر، وبعدين ابعتلي نفس الكود تاني هنا.",
                                           "en": "You don't have a public Telegram username (@) yet — you need one before you can verify your account. Go to Telegram's Settings → Username, set one, then send me the same code again here.",
                                           "pt": "Você ainda não tem um nome de usuário público do Telegram (@) — você precisa de um antes de verificar sua conta. Vá em Configurações → Nome de usuário no Telegram, defina um, e me envie o mesmo código aqui novamente.",
                                           "tr": "Henüz genel bir Telegram kullanıcı adınız (@) yok — hesabınızı doğrulamadan önce bir tane edinmeniz gerekiyor. Telegram'ın Ayarlar → Kullanıcı Adı bölümüne gidin, bir tane belirleyin, sonra aynı kodu bana tekrar gönderin.",
                                           "id": "Anda belum memiliki nama pengguna Telegram publik (@) — Anda memerlukannya sebelum dapat memverifikasi akun Anda. Buka Pengaturan → Nama Pengguna di Telegram, atur satu, lalu kirimkan kode yang sama kepada saya lagi di sini."},
    "telegram_bot_username_synced_msg": {"ar": "لاحظنا إنك عملت يوزر تليجرام عام (@{username}) — حدّثنا بروفايلك في البنك تلقائيًا عشان يبقى مطابق. ✅",
                                           "en": "We noticed you set a public Telegram username (@{username}) — we've automatically updated your bank profile to match. ✅",
                                           "pt": "Percebemos que você definiu um nome de usuário público do Telegram (@{username}) — atualizamos automaticamente seu perfil no banco para corresponder. ✅",
                                           "tr": "Genel bir Telegram kullanıcı adı (@{username}) belirlediğinizi fark ettik — banka profilinizi otomatik olarak buna göre güncelledik. ✅",
                                           "id": "Kami melihat Anda telah mengatur nama pengguna Telegram publik (@{username}) — kami otomatis memperbarui profil bank Anda agar sesuai. ✅"},
    "bot_menu_title": {"ar": "🏦 قائمة GNID BANK — اختار من الأزرار تحت:", "en": "🏦 GNID BANK Menu — choose from the buttons below:", "pt": "🏦 Menu GNID BANK — escolha entre os botões abaixo:", "tr": "🏦 GNID BANK Menüsü — aşağıdaki düğmelerden seçin:", "id": "🏦 Menu GNID BANK — pilih dari tombol di bawah:"},
    "bot_menu_open_site_btn": {"ar": "🌐 افتح الموقع", "en": "🌐 Open Website", "pt": "🌐 Abrir Site", "tr": "🌐 Web Sitesini Aç", "id": "🌐 Buka Situs Web"},
    "bot_menu_balance_btn": {"ar": "💰 رصيدي وإحصائياتي", "en": "💰 My Balance & Stats", "pt": "💰 Meu Saldo e Estatísticas", "tr": "💰 Bakiyem ve İstatistiklerim", "id": "💰 Saldo & Statistik Saya"},
    "bot_menu_deposit_help_btn": {"ar": "📥 إزاي أعمل إيداع؟", "en": "📥 How do I deposit?", "pt": "📥 Como faço um depósito?", "tr": "📥 Nasıl para yatırırım?", "id": "📥 Bagaimana cara setor?"},
    "bot_not_verified_msg": {"ar": "لازم توثق حسابك الأول. روح صفحة الإعدادات في الموقع واعمل \"إنشاء كود توثيق\".",
                               "en": "You need to verify your account first. Go to Settings on the site and click \"Generate Verification Code\".",
                               "pt": "Você precisa verificar sua conta primeiro. Vá até Configurações no site e clique em \"Gerar Código de Verificação\".",
                               "tr": "Önce hesabınızı doğrulamanız gerekir. Sitede Ayarlar'a gidin ve \"Doğrulama Kodu Oluştur\"a tıklayın.",
                               "id": "Anda perlu memverifikasi akun Anda terlebih dahulu. Buka Pengaturan di situs dan klik \"Buat Kode Verifikasi\"."},
    "bot_stats_msg": {"ar": "📊 <b>إحصائياتك يا {username}</b>\n\n💰 الرصيد: {balance}\n🏦 الاستثمارات النشطة: {active_count}\n💵 إجمالي المستثمر: {total_invested}\n📈 العائد المتوقع: {total_payout}\n📦 عدد الأسهم اللي معاك: {stocks_owned}\n💸 طلبات سحب معلقة: {pending_withdrawals}",
                        "en": "📊 <b>Your stats, {username}</b>\n\n💰 Balance: {balance}\n🏦 Active Investments: {active_count}\n💵 Total Invested: {total_invested}\n📈 Expected Payout: {total_payout}\n📦 Stocks Owned: {stocks_owned}\n💸 Pending Withdrawals: {pending_withdrawals}",
                        "pt": "📊 <b>Suas estatísticas, {username}</b>\n\n💰 Saldo: {balance}\n🏦 Investimentos Ativos: {active_count}\n💵 Total Investido: {total_invested}\n📈 Retorno Esperado: {total_payout}\n📦 Ações Possuídas: {stocks_owned}\n💸 Saques Pendentes: {pending_withdrawals}",
                        "tr": "📊 <b>İstatistikleriniz, {username}</b>\n\n💰 Bakiye: {balance}\n🏦 Aktif Yatırımlar: {active_count}\n💵 Toplam Yatırılan: {total_invested}\n📈 Beklenen Getiri: {total_payout}\n📦 Sahip Olunan Hisseler: {stocks_owned}\n💸 Bekleyen Para Çekmeleri: {pending_withdrawals}",
                        "id": "📊 <b>Statistik Anda, {username}</b>\n\n💰 Saldo: {balance}\n🏦 Investasi Aktif: {active_count}\n💵 Total Diinvestasikan: {total_invested}\n📈 Perkiraan Pembayaran: {total_payout}\n📦 Saham Dimiliki: {stocks_owned}\n💸 Penarikan Tertunda: {pending_withdrawals}"},
    "bot_deposit_help_msg": {"ar": "📥 <b>إزاي تعمل إيداع؟</b>\n\n1️⃣ روح صفحة \"إضافة رصيد\" في الموقع: {site_url}/deposit\n2️⃣ هتلاقي المبلغ المظبوط اللي لازم تبعته (بيتحسب من المبلغ اللي عايزه + آيدي حسابك)\n3️⃣ حوّل المبلغ ده جوه اللعبة للحساب الرسمي المكتوب في الصفحة\n4️⃣ استنى دقيقة والرصيد هيتضاف تلقائي",
                               "en": "📥 <b>How to make a deposit</b>\n\n1️⃣ Go to the \"Add Balance\" page on the site: {site_url}/deposit\n2️⃣ You'll see the exact amount to send (calculated from the amount you want + your account ID)\n3️⃣ Transfer that amount in-game to the official account shown on the page\n4️⃣ Wait about a minute and your balance will be added automatically",
                               "pt": "📥 <b>Como fazer um depósito</b>\n\n1️⃣ Vá até a página \"Adicionar Saldo\" no site: {site_url}/deposit\n2️⃣ Você verá o valor exato a enviar (calculado a partir do valor desejado + seu ID de conta)\n3️⃣ Transfira esse valor dentro do jogo para a conta oficial mostrada na página\n4️⃣ Espere cerca de um minuto e seu saldo será adicionado automaticamente",
                               "tr": "📥 <b>Nasıl para yatırılır</b>\n\n1️⃣ Sitede \"Bakiye Ekle\" sayfasına gidin: {site_url}/deposit\n2️⃣ Gönderilecek tam tutarı göreceksiniz (istediğiniz tutar + hesap kimliğinizden hesaplanır)\n3️⃣ Bu tutarı oyun içinde sayfada gösterilen resmi hesaba transfer edin\n4️⃣ Yaklaşık bir dakika bekleyin, bakiyeniz otomatik olarak eklenecektir",
                               "id": "📥 <b>Cara melakukan setoran</b>\n\n1️⃣ Buka halaman \"Tambah Saldo\" di situs: {site_url}/deposit\n2️⃣ Anda akan melihat jumlah pasti yang harus dikirim (dihitung dari jumlah yang Anda inginkan + ID akun Anda)\n3️⃣ Transfer jumlah tersebut dalam game ke akun resmi yang ditampilkan di halaman\n4️⃣ Tunggu sekitar satu menit dan saldo Anda akan ditambahkan secara otomatis"},
    "flash_telegram_empty": {"ar": "لازم تكتب يوزر تليجرام", "en": "Telegram username is required", "pt": "O usuário do Telegram é obrigatório", "tr": "Telegram kullanıcı adı gerekli", "id": "Nama pengguna Telegram wajib diisi"},
    "flash_telegram_invalid_format": {"ar": "يوزر التليجرام غير صحيح — لازم يكون من 5 لـ32 حرف، حروف إنجليزي وأرقام و(_) بس، من غير مسافات، ولازم يبدأ بحرف.",
                                        "en": "Invalid Telegram username — must be 5-32 characters, English letters/numbers/underscores only, no spaces, and must start with a letter.",
                                        "pt": "Nome de usuário do Telegram inválido — deve ter de 5 a 32 caracteres, apenas letras/números/sublinhados, sem espaços, e deve começar com uma letra.",
                                        "tr": "Geçersiz Telegram kullanıcı adı — 5-32 karakter olmalı, yalnızca harf/rakam/alt çizgi içermeli, boşluk olmamalı ve bir harfle başlamalı.",
                                        "id": "Nama pengguna Telegram tidak valid — harus 5-32 karakter, hanya huruf/angka/garis bawah, tanpa spasi, dan harus dimulai dengan huruf."},
    "flash_loan_needs_verification": {"ar": "لازم توثّق حسابك بتليجرام الأول عشان تقدر تطلب دين.",
                                        "en": "You must verify your account with Telegram before you can request a loan.",
                                        "pt": "Você deve verificar sua conta pelo Telegram antes de poder solicitar um empréstimo.",
                                        "tr": "Kredi talep edebilmek için önce hesabınızı Telegram ile doğrulamalısınız.",
                                        "id": "Anda harus memverifikasi akun Anda dengan Telegram sebelum dapat mengajukan pinjaman."},
    "loan_verify_required_notice": {"ar": "لازم توثّق حسابك بتليجرام الأول عشان تقدر تطلب دين.",
                                      "en": "You must verify your account with Telegram before you can request a loan.",
                                      "pt": "Você deve verificar sua conta pelo Telegram antes de poder solicitar um empréstimo.",
                                      "tr": "Kredi talep edebilmek için önce hesabınızı Telegram ile doğrulamalısınız.",
                                      "id": "Anda harus memverifikasi akun Anda dengan Telegram sebelum dapat mengajukan pinjaman."},
    "your_id_label": {"ar": "آيديك", "en": "Your ID", "pt": "Seu ID", "tr": "Kimliğiniz", "id": "ID Anda"},
    "menu_label": {"ar": "القائمة", "en": "Menu", "pt": "Menu", "tr": "Menü", "id": "Menu"},
    "admin_section_label": {"ar": "أدوات الأدمن", "en": "Admin Tools", "pt": "Ferramentas de Admin", "tr": "Yönetici Araçları", "id": "Alat Admin"},
    "balance_word": {"ar": "رصيد", "en": "balance", "pt": "saldo", "tr": "bakiye", "id": "saldo"},

    "register_title": {"ar": "فتح حساب جديد", "en": "Create a New Account", "pt": "Criar Nova Conta", "tr": "Yeni Hesap Oluştur", "id": "Buat Akun Baru"},
    "register_lede": {"ar": "سجل عشان تربط حسابك وتبدأ تتعامل مع البنك.",
                       "en": "Register to link your account and start using the bank.",
                       "pt": "Cadastre-se para vincular sua conta e começar a usar o banco.", "tr": "Hesabınızı bağlamak ve bankayı kullanmaya başlamak için kayıt olun.", "id": "Daftar untuk menautkan akun Anda dan mulai menggunakan bank."},
    "username": {"ar": "اسم المستخدم", "en": "Username", "pt": "Nome de usuário", "tr": "Kullanıcı Adı", "id": "Nama Pengguna"},
    "telegram_user": {"ar": "يوزر التليجرام", "en": "Telegram username", "pt": "Usuário do Telegram", "tr": "Telegram kullanıcı adı", "id": "Nama pengguna Telegram"},
    "password": {"ar": "كلمة السر", "en": "Password", "pt": "Senha", "tr": "Şifre", "id": "Kata Sandi"},
    "register_btn": {"ar": "تسجيل", "en": "Register", "pt": "Cadastrar", "tr": "Kayıt Ol", "id": "Daftar"},
    "have_account": {"ar": "عندك حساب بالفعل؟", "en": "Already have an account?", "pt": "Já tem uma conta?", "tr": "Zaten bir hesabınız var mı?", "id": "Sudah punya akun?"},
    "login_link": {"ar": "سجل دخول", "en": "Log in", "pt": "Entrar", "tr": "Giriş Yap", "id": "Masuk"},

    "login_title": {"ar": "تسجيل الدخول", "en": "Log In", "pt": "Entrar", "tr": "Giriş Yap", "id": "Masuk"},
    "login_lede": {"ar": "ادخل بياناتك عشان تدخل حسابك.",
                    "en": "Enter your details to access your account.",
                    "pt": "Insira seus dados para acessar sua conta.", "tr": "Hesabınıza erişmek için bilgilerinizi girin.", "id": "Masukkan detail Anda untuk mengakses akun Anda."},
    "login_btn": {"ar": "دخول", "en": "Log In", "pt": "Entrar", "tr": "Giriş Yap", "id": "Masuk"},
    "no_account": {"ar": "مفيش حساب؟", "en": "No account?", "pt": "Não tem conta?", "tr": "Hesabınız yok mu?", "id": "Belum punya akun?"},
    "register_link": {"ar": "اعمل واحد جديد", "en": "Create one", "pt": "Criar uma", "tr": "Bir tane oluşturun", "id": "Buat satu"},

    "auth_tagline": {"ar": "بنك GNID الرسمي للعبة Diplomacia — أضف رصيد، استثمر، اتاجر في الأسهم، وتابع فلوسك كله في مكان واحد.",
                       "en": "The official GNID Bank for the Diplomacia game — add balance, invest, trade stocks, and track all your money in one place.",
                       "pt": "O banco oficial GNID do jogo Diplomacia — adicione saldo, invista, negocie ações e acompanhe todo o seu dinheiro em um só lugar.",
                       "tr": "Diplomacia oyununun resmi GNID Bankası — bakiye ekleyin, yatırım yapın, hisse alıp satın ve tüm paranızı tek yerden takip edin.",
                       "id": "Bank resmi GNID untuk game Diplomacia — tambah saldo, berinvestasi, perdagangkan saham, dan pantau semua uang Anda di satu tempat."},
    "telegram_group_link": {"ar": "جروب التليجرام", "en": "Telegram Group", "pt": "Grupo do Telegram", "tr": "Telegram Grubu", "id": "Grup Telegram"},
    "play_game_link": {"ar": "العب اللعبة", "en": "Play the Game", "pt": "Jogar o Jogo", "tr": "Oyunu Oyna", "id": "Mainkan Game"},

    "link_title": {"ar": "ربط حساب اللعبة", "en": "Link Game Account", "pt": "Vincular Conta do Jogo", "tr": "Oyun Hesabını Bağla", "id": "Tautkan Akun Game"},
    "link_lede": {"ar": "اربط اسم المستخدم بتاعك في اللعبة عشان نوصل بيانات حسابك ببعض.",
                  "en": "Link your in-game username so we can connect your accounts.",
                  "pt": "Vincule seu nome de usuário no jogo para conectarmos suas contas.", "tr": "Hesaplarınızı bağlayabilmemiz için oyun içi kullanıcı adınızı bağlayın.", "id": "Tautkan nama pengguna dalam game Anda agar kami dapat menghubungkan akun Anda."},
    "game_username": {"ar": "اسم المستخدم في اللعبة", "en": "In-game username", "pt": "Nome de usuário no jogo", "tr": "Oyun içi kullanıcı adı", "id": "Nama pengguna dalam game"},
    "game_uid": {"ar": "آي دي اللعبة", "en": "Game UID", "pt": "UID do jogo", "tr": "Oyun UID", "id": "UID Game"},
    "link_btn": {"ar": "ربط الحساب", "en": "Link Account", "pt": "Vincular Conta", "tr": "Hesabı Bağla", "id": "Tautkan Akun"},

    "account_summary": {"ar": "ملخص الحساب", "en": "Account Summary", "pt": "Resumo da Conta", "tr": "Hesap Özeti", "id": "Ringkasan Akun"},
    "greeting_hello": {"ar": "أهلًا", "en": "Hello", "pt": "Olá", "tr": "Merhaba", "id": "Halo"},
    "complete_profile_title": {"ar": "كمّل توثيق حسابك", "en": "Complete Your Profile", "pt": "Complete seu Perfil", "tr": "Profilinizi Tamamlayın", "id": "Lengkapi Profil Anda"},
    "complete_profile_body": {"ar": "وثّق حسابك بتليجرام عشان يبقى موثوق أكتر — يستغرق ثواني بس.",
                                "en": "Verify your account with Telegram to make it more trustworthy — takes just seconds.",
                                "pt": "Verifique sua conta com o Telegram para torná-la mais confiável — leva apenas segundos.",
                                "tr": "Hesabınızı daha güvenilir kılmak için Telegram ile doğrulayın — sadece saniyeler sürer.",
                                "id": "Verifikasi akun Anda dengan Telegram agar lebih terpercaya — hanya butuh beberapa detik."},
    "quick_actions_title": {"ar": "إجراءات سريعة", "en": "Quick Actions", "pt": "Ações Rápidas", "tr": "Hızlı İşlemler", "id": "Tindakan Cepat"},
    "stat_active_investments": {"ar": "استثمارات شغالة", "en": "Active Investments", "pt": "Investimentos Ativos", "tr": "Aktif Yatırımlar", "id": "Investasi Aktif"},
    "stat_total_invested": {"ar": "إجمالي المستثمر دلوقتي", "en": "Currently Invested", "pt": "Investido Atualmente", "tr": "Şu An Yatırılan", "id": "Sedang Diinvestasikan"},
    "stat_expected_payout": {"ar": "العائد المتوقع الإجمالي", "en": "Total Expected Payout", "pt": "Retorno Total Esperado", "tr": "Beklenen Toplam Getiri", "id": "Total Perkiraan Pembayaran"},
    "stat_pending_withdrawals": {"ar": "طلبات سحب قيد الانتظار", "en": "Pending Withdrawals", "pt": "Saques Pendentes", "tr": "Bekleyen Para Çekme İşlemleri", "id": "Penarikan Tertunda"},
    "stat_holdings_count": {"ar": "أنواع الأسهم اللي معاك", "en": "Stocks You Own", "pt": "Ações que Você Possui", "tr": "Sahip Olduğunuz Hisseler", "id": "Saham yang Anda Miliki"},
    "stat_holdings_value": {"ar": "قيمة الأسهم المملوكة", "en": "Value of Owned Stocks", "pt": "Valor das Ações Possuídas", "tr": "Sahip Olunan Hisselerin Değeri", "id": "Nilai Saham yang Dimiliki"},
    "view_investments_link": {"ar": "شوف تفاصيل الاستثمارات", "en": "View investment details", "pt": "Ver detalhes dos investimentos", "tr": "Yatırım detaylarını görüntüle", "id": "Lihat detail investasi"},
    "next_maturity_label": {"ar": "أقرب استحقاق", "en": "Next Maturity", "pt": "Próximo Vencimento", "tr": "Sonraki Vade", "id": "Jatuh Tempo Berikutnya"},
    "no_pending_withdrawals_dash": {"ar": "لا يوجد", "en": "None", "pt": "Nenhum", "tr": "Yok", "id": "Tidak ada"},
    "qa_add_balance": {"ar": "أضف رصيد", "en": "Add Balance", "pt": "Adicionar Saldo", "tr": "Bakiye Ekle", "id": "Tambah Saldo"},
    "qa_market": {"ar": "ادخل الأسهم", "en": "Go to Stocks", "pt": "Ir para Ações", "tr": "Hisselere Git", "id": "Ke Saham"},
    "qa_invest": {"ar": "استثمر فلوسك", "en": "Invest Your Money", "pt": "Invista seu Dinheiro", "tr": "Paranı Yatır", "id": "Investasikan Uang Anda"},
    "qa_withdraw": {"ar": "اسحب رصيد", "en": "Withdraw Funds", "pt": "Sacar Fundos", "tr": "Para Çek", "id": "Tarik Dana"},
    "qa_loans": {"ar": "طلب دين", "en": "Request a Loan", "pt": "Solicitar Empréstimo", "tr": "Kredi Talep Et", "id": "Ajukan Pinjaman"},
    "qa_settings": {"ar": "الإعدادات", "en": "Settings", "pt": "Configurações", "tr": "Ayarlar", "id": "Pengaturan"},
    "qa_guide": {"ar": "شرح التطبيق", "en": "App Guide", "pt": "Guia do App", "tr": "Uygulama Rehberi", "id": "Panduan Aplikasi"},
    "your_account_id": {"ar": "آي دي حسابك البنكي", "en": "Your bank account ID", "pt": "Seu ID bancário", "tr": "Banka hesap kimliğiniz", "id": "ID akun bank Anda"},
    "telegram_label": {"ar": "تليجرام", "en": "Telegram", "pt": "Telegram", "tr": "Telegram", "id": "Telegram"},
    "telegram_no_public_username": {"ar": "من غير يوزر عام، بالاسم بس", "en": "no public username, name only",
                                      "pt": "sem usuário público, apenas o nome", "tr": "genel kullanıcı adı yok, sadece ad",
                                      "id": "tanpa nama pengguna publik, hanya nama"},
    "linked_game": {"ar": "اسم اللعبة المربوط", "en": "Linked game account", "pt": "Conta do jogo vinculada", "tr": "Bağlı oyun hesabı", "id": "Akun game tertaut"},
    "not_linked": {"ar": "غير مربوط", "en": "Not linked", "pt": "Não vinculada", "tr": "Bağlı değil", "id": "Belum tertaut"},
    "my_stocks": {"ar": "الأسهم اللي معايا", "en": "My Stocks", "pt": "Minhas Ações", "tr": "Hisselerim", "id": "Saham Saya"},
    "no_stocks_yet": {"ar": "مفيش أسهم لسه. زور", "en": "No stocks yet. Visit the", "pt": "Sem ações ainda. Visite o", "tr": "Henüz hisse yok. Ziyaret et:", "id": "Belum ada saham. Kunjungi"},
    "market_word": {"ar": "السوق", "en": "market", "pt": "mercado", "tr": "piyasa", "id": "pasar"},
    "start_here": {"ar": "عشان تبدأ.", "en": "to get started.", "pt": "para começar.", "tr": "başlamak için.", "id": "untuk memulai."},

    "transfer_title": {"ar": "تحويل رصيد", "en": "Transfer Balance", "pt": "Transferir Saldo", "tr": "Bakiye Transferi", "id": "Transfer Saldo"},
    "transfer_lede": {"ar": "حوّل جزء من رصيدك لحساب تاني بالآي دي البنكي بتاعه.",
                       "en": "Send part of your balance to another account using their bank ID.",
                       "pt": "Envie parte do seu saldo para outra conta usando o ID bancário dela.", "tr": "Banka kimliklerini kullanarak bakiyenizin bir kısmını başka bir hesaba gönderin.", "id": "Kirim sebagian saldo Anda ke akun lain menggunakan ID bank mereka."},
    "recipient_id": {"ar": "آي دي الحساب المستلم", "en": "Recipient account ID", "pt": "ID da conta destinatária", "tr": "Alıcı hesap kimliği", "id": "ID akun penerima"},
    "amount": {"ar": "المبلغ", "en": "Amount", "pt": "Valor", "tr": "Tutar", "id": "Jumlah"},
    "note_optional": {"ar": "ملاحظة (اختياري)", "en": "Note (optional)", "pt": "Nota (opcional)", "tr": "Not (isteğe bağlı)", "id": "Catatan (opsional)"},
    "note_reason": {"ar": "سبب التحويل", "en": "Reason for transfer", "pt": "Motivo da transferência", "tr": "Transfer nedeni", "id": "Alasan transfer"},
    "execute_transfer": {"ar": "تنفيذ التحويل", "en": "Send Transfer", "pt": "Enviar Transferência", "tr": "Transferi Gönder", "id": "Kirim Transfer"},

    "ipo_title": {"ar": "الطرح الرسمي (IPO)", "en": "Official Offering (IPO)", "pt": "Oferta Oficial (IPO)", "tr": "Resmi Halka Arz (IPO)", "id": "Penawaran Resmi (IPO)"},
    "market_index_title": {"ar": "مؤشر سوق GNID", "en": "GNID Market Index", "pt": "Índice de Mercado GNID", "tr": "GNID Piyasa Endeksi", "id": "Indeks Pasar GNID"},
    "market_index_lede": {"ar": "إجمالي القيمة السوقية لكل الأسهم مجتمعة، محسوبة من كل صفقة حصلت في السوق.",
                            "en": "Total market capitalization across all stocks combined, tracked from every trade that happens in the market.",
                            "pt": "Capitalização de mercado total de todas as ações combinadas, rastreada a partir de cada negociação no mercado.", "tr": "Tüm hisselerin toplam piyasa değeri, piyasada gerçekleşen her işlemden takip edilir.", "id": "Total kapitalisasi pasar dari semua saham gabungan, dilacak dari setiap transaksi yang terjadi di pasar."},
    "ipo_lede": {"ar": "أسهم متاحة للشراء المباشر من البنك.",
                 "en": "Stocks available for direct purchase from the bank.",
                 "pt": "Ações disponíveis para compra direta do banco.", "tr": "Bankadan doğrudan satın alınabilecek hisseler.", "id": "Saham yang tersedia untuk dibeli langsung dari bank."},
    "symbol": {"ar": "الرمز", "en": "Symbol", "pt": "Símbolo", "tr": "Sembol", "id": "Simbol"},
    "name_col": {"ar": "الاسم", "en": "Name", "pt": "Nome", "tr": "İsim", "id": "Nama"},
    "price": {"ar": "السعر", "en": "Price", "pt": "Preço", "tr": "Fiyat", "id": "Harga"},
    "available": {"ar": "المتاح", "en": "Available", "pt": "Disponível", "tr": "Mevcut", "id": "Tersedia"},
    "buy": {"ar": "شراء", "en": "Buy", "pt": "Comprar", "tr": "Satın Al", "id": "Beli"},
    "no_stocks_offered": {"ar": "مفيش أسهم مطروحة من البنك حاليًا.",
                           "en": "No stocks currently offered by the bank.",
                           "pt": "Nenhuma ação oferecida pelo banco no momento.", "tr": "Banka şu anda hisse sunmuyor.", "id": "Bank saat ini tidak menawarkan saham."},
    "trading_market": {"ar": "سوق التداول", "en": "Trading Market", "pt": "Mercado de Negociação", "tr": "İşlem Piyasası", "id": "Pasar Perdagangan"},
    "trading_lede": {"ar": "اعمل أمر بيع أو شراء يتقابل تلقائيًا مع أوامر باقي المستخدمين.",
                      "en": "Place a buy/sell order that matches automatically with other users' orders.",
                      "pt": "Faça uma ordem de compra/venda que combina automaticamente com outros usuários.", "tr": "Diğer kullanıcıların emirleriyle otomatik olarak eşleşen bir alış/satış emri verin.", "id": "Tempatkan order beli/jual yang otomatis cocok dengan order pengguna lain."},
    "sell": {"ar": "بيع", "en": "Sell", "pt": "Vender", "tr": "Sat", "id": "Jual"},
    "quantity": {"ar": "الكمية", "en": "Quantity", "pt": "Quantidade", "tr": "Miktar", "id": "Jumlah"},
    "owned_col": {"ar": "الأسهم المملوكة", "en": "Owned Shares", "pt": "Ações Possuídas", "tr": "Sahip Olunan Hisseler", "id": "Saham yang Dimiliki"},
    "filter_all": {"ar": "الكل", "en": "All", "pt": "Todas", "tr": "Tümü", "id": "Semua"},
    "execute_order": {"ar": "تنفيذ الأمر", "en": "Place Order", "pt": "Executar Ordem", "tr": "Emir Ver", "id": "Pasang Order"},
    "open_orders": {"ar": "الأوامر المفتوحة", "en": "Open Orders", "pt": "Ordens Abertas", "tr": "Açık Emirler", "id": "Order Terbuka"},
    "user_col": {"ar": "المستخدم", "en": "User", "pt": "Usuário", "tr": "Kullanıcı", "id": "Pengguna"},
    "type_col": {"ar": "النوع", "en": "Type", "pt": "Tipo", "tr": "Tür", "id": "Tipe"},
    "cancel": {"ar": "إلغاء", "en": "Cancel", "pt": "Cancelar", "tr": "İptal", "id": "Batal"},
    "no_open_orders": {"ar": "مفيش أوامر مفتوحة حاليًا.", "en": "No open orders currently.", "pt": "Nenhuma ordem aberta no momento.", "tr": "Şu anda açık emir yok.", "id": "Saat ini tidak ada order terbuka."},
    "my_trades_title": {"ar": "سجل صفقاتي", "en": "My Trades", "pt": "Minhas Negociações", "tr": "İşlemlerim", "id": "Transaksi Saya"},
    "my_trades_lede": {"ar": "كل عمليات البيع والشراء اللي عملتها في سوق الأسهم.", "en": "All your buy and sell trades in the stock market.", "pt": "Todas as suas negociações de compra e venda no mercado de ações.", "tr": "Hisse senedi piyasasındaki tüm alım/satım işlemleriniz.", "id": "Semua transaksi beli dan jual Anda di pasar saham."},
    "no_my_trades_yet": {"ar": "لسه معملتش أي صفقة بيع أو شراء.", "en": "You haven't made any buy or sell trades yet.", "pt": "Você ainda não fez nenhuma negociação de compra ou venda.", "tr": "Henüz hiç alım/satım işlemi yapmadınız.", "id": "Anda belum melakukan transaksi beli atau jual apa pun."},
    "total_col": {"ar": "الإجمالي", "en": "Total", "pt": "Total", "tr": "Toplam", "id": "Total"},

    "manage_stocks_title": {"ar": "إدارة الأسهم", "en": "Manage Stocks", "pt": "Gerenciar Ações", "tr": "Hisseleri Yönet", "id": "Kelola Saham"},
    "manage_stocks_lede": {"ar": "أضف سهم جديد أو زوّد كمية سهم موجود.",
                            "en": "Add a new stock or increase an existing one's supply.",
                            "pt": "Adicione uma nova ação ou aumente a oferta de uma existente.", "tr": "Yeni bir hisse ekleyin veya mevcut birinin arzını artırın.", "id": "Tambahkan saham baru atau tingkatkan pasokan yang sudah ada."},
    "stock_symbol": {"ar": "رمز السهم", "en": "Stock symbol", "pt": "Símbolo da ação", "tr": "Hisse sembolü", "id": "Simbol saham"},
    "stock_name": {"ar": "اسم الشركة", "en": "Company Name", "pt": "Nome da Empresa", "tr": "Şirket Adı", "id": "Nama Perusahaan"},
    "sale_price": {"ar": "سعر السهم الواحد", "en": "Price per Share", "pt": "Preço por Ação", "tr": "Hisse Başına Fiyat", "id": "Harga per Saham"},
    "save_btn": {"ar": "حفظ", "en": "Save", "pt": "Salvar", "tr": "Kaydet", "id": "Simpan"},
    "current_stocks": {"ar": "الأسهم الحالية", "en": "Current Stocks", "pt": "Ações Atuais", "tr": "Mevcut Hisseler", "id": "Saham Saat Ini"},
    "no_stocks_added": {"ar": "مفيش أسهم مضافة لسه.", "en": "No stocks added yet.", "pt": "Nenhuma ação adicionada ainda.", "tr": "Henüz hisse eklenmedi.", "id": "Belum ada saham yang ditambahkan."},
    "stock_icon_label": {"ar": "اختار أيقونة العملة", "en": "Choose a currency icon", "pt": "Escolha um ícone", "tr": "Bir para birimi simgesi seçin", "id": "Pilih ikon mata uang"},
    "edit_btn": {"ar": "تعديل", "en": "Edit", "pt": "Editar", "tr": "Düzenle", "id": "Edit"},
    "delete_btn": {"ar": "حذف", "en": "Delete", "pt": "Excluir", "tr": "Sil", "id": "Hapus"},
    "company_description": {"ar": "وصف الشركة", "en": "Company Description", "pt": "Descrição da Empresa", "tr": "Şirket Açıklaması", "id": "Deskripsi Perusahaan"},
    "company_sector": {"ar": "قطاع الشركة", "en": "Sector", "pt": "Setor", "tr": "Sektör", "id": "Sektor"},
    "company_owner": {"ar": "مالك/مؤسس الشركة", "en": "Owner/Founder", "pt": "Proprietário/Fundador", "tr": "Sahip/Kurucu", "id": "Pemilik/Pendiri"},
    "company_owner_account_id": {"ar": "آيدي حساب المالك في البنك (اختياري)", "en": "Owner's Bank Account ID (optional)", "pt": "ID da Conta Bancária do Proprietário (opcional)", "tr": "Sahibin Banka Hesap Kimliği (isteğe bağlı)", "id": "ID Akun Bank Pemilik (opsional)"},
    "total_shares_label": {"ar": "إجمالي عدد الأسهم", "en": "Total Shares", "pt": "Total de Ações", "tr": "Toplam Hisse", "id": "Total Saham"},
    "total_shares_hint": {"ar": "سيبها فاضية لو عايز تحسبها تلقائي", "en": "Leave empty to auto-calculate", "pt": "Deixe em branco para calcular automaticamente", "tr": "Otomatik hesaplamak için boş bırakın", "id": "Kosongkan untuk hitung otomatis"},
    "company_profile_title": {"ar": "ملف الشركة", "en": "Company Profile", "pt": "Perfil da Empresa", "tr": "Şirket Profili", "id": "Profil Perusahaan"},
    "current_price_label": {"ar": "السعر الحالي", "en": "Current Price", "pt": "Preço Atual", "tr": "Güncel Fiyat", "id": "Harga Saat Ini"},
    "opening_price_label": {"ar": "سعر الافتتاح", "en": "Opening Price", "pt": "Preço de Abertura", "tr": "Açılış Fiyatı", "id": "Harga Pembukaan"},
    "high_price_label": {"ar": "أعلى سعر", "en": "Highest Price", "pt": "Preço Mais Alto", "tr": "En Yüksek Fiyat", "id": "Harga Tertinggi"},
    "low_price_label": {"ar": "أقل سعر", "en": "Lowest Price", "pt": "Preço Mais Baixo", "tr": "En Düşük Fiyat", "id": "Harga Terendah"},
    "price_change_label": {"ar": "التغيير", "en": "Change", "pt": "Variação", "tr": "Değişim", "id": "Perubahan"},
    "market_cap_label": {"ar": "القيمة السوقية", "en": "Market Cap", "pt": "Valor de Mercado", "tr": "Piyasa Değeri", "id": "Kapitalisasi Pasar"},
    "volume_label": {"ar": "حجم التداول", "en": "Volume", "pt": "Volume", "tr": "Hacim", "id": "Volume"},
    "total_shares_stat": {"ar": "إجمالي الأسهم", "en": "Total Shares", "pt": "Total de Ações", "tr": "Toplam Hisse", "id": "Total Saham"},
    "available_pct_label": {"ar": "نسبة المتاح للسوق", "en": "% Available on Market", "pt": "% Disponível no Mercado", "tr": "Piyasada Mevcut %", "id": "% Tersedia di Pasar"},
    "owned_pct_label": {"ar": "نسبة المملوكة", "en": "% Already Owned", "pt": "% Já Possuída", "tr": "Zaten Sahip Olunan %", "id": "% Sudah Dimiliki"},
    "listed_since_label": {"ar": "مطروحة منذ", "en": "Listed Since", "pt": "Listada Desde", "tr": "Listelenme Tarihi", "id": "Terdaftar Sejak"},
    "price_chart_title": {"ar": "حركة السعر", "en": "Price Chart", "pt": "Gráfico de Preço", "tr": "Fiyat Grafiği", "id": "Grafik Harga"},
    "range_all": {"ar": "الكل", "en": "All", "pt": "Tudo", "tr": "Tümü", "id": "Semua"},
    "no_trades_yet": {"ar": "مفيش صفقات حصلت على السهم ده لسه — السعر لسه هو سعر الطرح.",
                        "en": "No trades have happened on this stock yet — price is still the IPO price.",
                        "pt": "Ainda não houve negociações desta ação — o preço ainda é o preço de IPO.", "tr": "Bu hissede henüz işlem gerçekleşmedi — fiyat hâlâ IPO fiyatı.", "id": "Belum ada transaksi pada saham ini — harga masih harga IPO."},
    "trading_volume_title": {"ar": "حجم التداول", "en": "Trading Volume", "pt": "Volume de Negociação", "tr": "İşlem Hacmi", "id": "Volume Perdagangan"},
    "total_shares_traded": {"ar": "إجمالي الأسهم المتداولة", "en": "Total Shares Traded", "pt": "Total de Ações Negociadas", "tr": "İşlem Gören Toplam Hisse", "id": "Total Saham Diperdagangkan"},
    "total_trading_value": {"ar": "إجمالي قيمة التداول", "en": "Total Trading Value", "pt": "Valor Total Negociado", "tr": "Toplam İşlem Değeri", "id": "Total Nilai Perdagangan"},
    "transactions_count": {"ar": "عدد الصفقات", "en": "Transactions", "pt": "Transações", "tr": "İşlemler", "id": "Transaksi"},
    "avg_price_label": {"ar": "متوسط سعر الصفقة", "en": "Average Trade Price", "pt": "Preço Médio da Negociação", "tr": "Ortalama İşlem Fiyatı", "id": "Harga Rata-rata Transaksi"},
    "market_activity_title": {"ar": "آخر الصفقات", "en": "Recent Market Activity", "pt": "Atividade Recente do Mercado", "tr": "Son Piyasa Hareketleri", "id": "Aktivitas Pasar Terbaru"},
    "auto_price_move_hint": {"ar": "⚡ السعر ممكن يتحرك تلقائيًا كل ساعة بناءً على ضغط أوامر البيع/الشراء المفتوحة، حتى لو مفيش صفقة فعلية اتنفذت — علشان كده ممكن تلاقي السعر اتغير من غير أي صفقة جديدة في القايمة تحت.", "en": "⚡ The price can move automatically every hour based on open buy/sell order pressure, even without an actual trade executing — so you may see the price change without a new trade appearing below.", "pt": "⚡ O preço pode se mover automaticamente a cada hora com base na pressão de ordens de compra/venda abertas, mesmo sem uma negociação real ser executada — por isso você pode ver o preço mudar sem uma nova negociação aparecer abaixo.", "tr": "⚡ Fiyat, gerçek bir işlem gerçekleşmese bile açık alım/satım emri baskısına göre her saat otomatik olarak hareket edebilir - bu yüzden aşağıda yeni bir işlem görünmeden fiyatın değiştiğini görebilirsiniz.", "id": "⚡ Harga dapat bergerak secara otomatis setiap jam berdasarkan tekanan order beli/jual terbuka, bahkan tanpa transaksi nyata yang dieksekusi — jadi Anda mungkin melihat harga berubah tanpa transaksi baru muncul di bawah."},
    "no_activity_yet": {"ar": "مفيش نشاط تداول لسه.", "en": "No trading activity yet.", "pt": "Nenhuma atividade de negociação ainda.", "tr": "Henüz işlem hareketi yok.", "id": "Belum ada aktivitas perdagangan."},
    "buy_side": {"ar": "شراء", "en": "BUY", "pt": "COMPRA", "tr": "ALIŞ", "id": "BELI"},
    "sell_side": {"ar": "بيع", "en": "SELL", "pt": "VENDA", "tr": "SATIŞ", "id": "JUAL"},
    "ipo_source": {"ar": "طرح مباشر", "en": "IPO", "pt": "IPO", "tr": "IPO", "id": "IPO"},
    "deleted_user_label": {"ar": "حساب محذوف", "en": "Deleted account", "pt": "Conta excluída", "tr": "Silinmiş hesap", "id": "Akun dihapus"},
    "shareholders_title": {"ar": "كبار المساهمين", "en": "Top Shareholders", "pt": "Principais Acionistas", "tr": "En Büyük Hissedarlar", "id": "Pemegang Saham Teratas"},
    "no_shareholders_yet": {"ar": "محدش شارى من السهم ده لسه.", "en": "No one has bought this stock yet.", "pt": "Ninguém comprou esta ação ainda.", "tr": "Henüz kimse bu hisseyi satın almadı.", "id": "Belum ada yang membeli saham ini."},
    "flash_no_shareholders_yet": {"ar": "مفيش مساهمين بأسهم فعلية في الشركة دي لسه - مينفعش نوزع أرباح", "en": "This company has no shareholders with actual shares yet - can't distribute dividends", "pt": "Esta empresa ainda não tem acionistas com ações reais - não é possível distribuir dividendos", "tr": "Bu şirketin henüz gerçek hisseye sahip hissedarı yok - temettü dağıtılamaz", "id": "Perusahaan ini belum memiliki pemegang saham dengan saham nyata - tidak dapat mendistribusikan dividen"},
    "rank_col": {"ar": "الترتيب", "en": "Rank", "pt": "Posição", "tr": "Sıra", "id": "Peringkat"},
    "ownership_pct_col": {"ar": "نسبة الملكية", "en": "Ownership %", "pt": "% de Propriedade", "tr": "Sahiplik %", "id": "% Kepemilikan"},
    "holdings_value_col": {"ar": "قيمة الحيازة", "en": "Holdings Value", "pt": "Valor da Participação", "tr": "Varlık Değeri", "id": "Nilai Kepemilikan"},
    "global_rankings_title": {"ar": "قائمة كبار المستثمرين (كل الأسهم)", "en": "Top Investors Ranking (All Stocks)", "pt": "Ranking de Maiores Investidores (Todas as Ações)", "tr": "En İyi Yatırımcılar Sıralaması (Tüm Hisseler)", "id": "Peringkat Investor Teratas (Semua Saham)"},
    "company_col": {"ar": "الشركة", "en": "Company", "pt": "Empresa", "tr": "Şirket", "id": "Perusahaan"},
    "view_profile_link": {"ar": "شوف ملف الشركة →", "en": "View company profile →", "pt": "Ver perfil da empresa →", "tr": "Şirket profilini görüntüle →", "id": "Lihat profil perusahaan →"},
    "rankings_nav": {"ar": "المستثمرين", "en": "Investors", "pt": "Investidores", "tr": "Yatırımcılar", "id": "Investor"},
    "sort_gainers": {"ar": "الأعلى ارتفاعًا", "en": "Top Gainers", "pt": "Maiores Altas", "tr": "En Çok Yükselenler", "id": "Kenaikan Tertinggi"},
    "sort_losers": {"ar": "الأعلى انخفاضًا", "en": "Top Losers", "pt": "Maiores Baixas", "tr": "En Çok Düşenler", "id": "Penurunan Tertinggi"},
    "sort_volume": {"ar": "الأعلى تداولًا", "en": "Most Traded", "pt": "Mais Negociadas", "tr": "En Çok İşlem Gören", "id": "Paling Banyak Diperdagangkan"},
    "sort_newest": {"ar": "الأحدث", "en": "Newest", "pt": "Mais Recentes", "tr": "En Yeni", "id": "Terbaru"},
    "sort_default": {"ar": "الكل", "en": "All", "pt": "Todas", "tr": "Tümü", "id": "Semua"},
    "full_activity_log": {"ar": "السجل الكامل", "en": "Full Activity Log", "pt": "Registro Completo de Atividades", "tr": "Tam Etkinlik Günlüğü", "id": "Log Aktivitas Lengkap"},
    "full_activity_title": {"ar": "السجل الكامل", "en": "Full Activity Log", "pt": "Registro Completo de Atividades", "tr": "Tam Etkinlik Günlüğü", "id": "Log Aktivitas Lengkap"},
    "full_activity_lede": {"ar": "كل التحويلات (إيداع/سحب)، الاستثمارات، وعمليات البيع والشراء في مكان واحد. دوس على أي قسم عشان تفتحه.",
                            "en": "All transfers (deposits/withdrawals), investments, and buy/sell trades in one place. Click any section to expand it.",
                            "pt": "Todas as transferências (depósitos/saques), investimentos e negociações de compra/venda em um só lugar. Clique em qualquer seção para expandi-la.", "tr": "Tüm transferler (yatırma/çekme), yatırımlar ve alış/satış işlemleri tek yerde. Genişletmek için herhangi bir bölüme tıklayın.", "id": "Semua transfer (setor/tarik), investasi, dan transaksi beli/jual dalam satu tempat. Klik bagian mana pun untuk memperluasnya."},
    "section_deposits": {"ar": "💰 الإيداعات", "en": "💰 Deposits", "pt": "💰 Depósitos", "tr": "💰 Para Yatırma", "id": "💰 Setoran"},
    "section_needs_review": {"ar": "⚠️ محتاج مراجعة يدوية", "en": "⚠️ Needs Manual Review", "pt": "⚠️ Precisa de Revisão Manual", "tr": "⚠️ Manuel İnceleme Gerekiyor", "id": "⚠️ Perlu Tinjauan Manual"},
    "deposits_log_moved_note": {"ar": "سجل الإيداعات والتحويلات بقى في:", "en": "The deposits and transfers log has moved to:", "pt": "O registro de depósitos e transferências foi movido para:", "tr": "Yatırma ve transfer günlüğü şuraya taşındı:", "id": "Log setoran dan transfer telah dipindahkan ke:"},
    "section_withdrawals": {"ar": "💸 السحوبات", "en": "💸 Withdrawals", "pt": "💸 Saques", "tr": "💸 Para Çekme", "id": "💸 Penarikan"},
    "section_investments": {"ar": "🏦 الاستثمارات", "en": "🏦 Investments", "pt": "🏦 Investimentos", "tr": "🏦 Yatırımlar", "id": "🏦 Investasi"},
    "section_loans": {"ar": "🤝 الديون", "en": "🤝 Loans", "pt": "🤝 Empréstimos", "tr": "🤝 Krediler", "id": "🤝 Pinjaman"},
    "section_trades": {"ar": "📈 البيع والشراء", "en": "📈 Buy/Sell Trades", "pt": "📈 Negociações", "tr": "📈 Alış/Satış İşlemleri", "id": "📈 Transaksi Beli/Jual"},
    "section_admin_actions": {"ar": "⚙️ إجراءات الأدمن", "en": "⚙️ Admin Actions", "pt": "⚙️ Ações do Admin", "tr": "⚙️ Yönetici İşlemleri", "id": "⚙️ Tindakan Admin"},
    "admin_col": {"ar": "الأدمن", "en": "Admin", "pt": "Admin", "tr": "Yönetici", "id": "Admin"},
    "action_col": {"ar": "الإجراء", "en": "Action", "pt": "Ação", "tr": "İşlem", "id": "Tindakan"},
    "target_user_col": {"ar": "الحساب المتأثر", "en": "Affected Account", "pt": "Conta Afetada", "tr": "Etkilenen Hesap", "id": "Akun Terdampak"},
    "action_balance_add": {"ar": "إضافة رصيد", "en": "Balance Added", "pt": "Saldo Adicionado", "tr": "Bakiye Eklendi", "id": "Saldo Ditambahkan"},
    "action_balance_subtract": {"ar": "خصم رصيد", "en": "Balance Deducted", "pt": "Saldo Deduzido", "tr": "Bakiyeden Düşüldü", "id": "Saldo Dikurangi"},
    "action_password_change": {"ar": "تغيير كلمة السر", "en": "Password Changed", "pt": "Senha Alterada", "tr": "Şifre Değiştirildi", "id": "Kata Sandi Diubah"},
    "action_user_unfreeze": {"ar": "فك تجميد حساب", "en": "Account Unfrozen", "pt": "Conta Descongelada", "tr": "Hesap Dondurması Kaldırıldı", "id": "Akun Dicairkan"},
    "action_data_backup_export": {"ar": "تصدير نسخة احتياطية للبيانات", "en": "Data Backup Exported", "pt": "Backup de Dados Exportado", "tr": "Veri Yedeği Dışa Aktarıldı", "id": "Cadangan Data Diekspor"},
    "action_user_delete": {"ar": "حذف حساب", "en": "Account Deleted", "pt": "Conta Excluída", "tr": "Hesap Silindi", "id": "Akun Dihapus"},
    "action_shares_to_treasury": {"ar": "تحويل أسهم للخزينة", "en": "Shares Moved to Treasury", "pt": "Ações Movidas para o Tesouro", "tr": "Hisseler Hazineye Taşındı", "id": "Saham Dipindahkan ke Kas"},
    "action_shares_from_treasury": {"ar": "تحويل أسهم من الخزينة", "en": "Shares Moved from Treasury", "pt": "Ações Movidas do Tesouro", "tr": "Hisseler Hazineden Taşındı", "id": "Saham Dipindahkan dari Kas"},
    "no_admin_actions_yet": {"ar": "مفيش إجراءات أدمن مسجلة لسه.", "en": "No admin actions recorded yet.", "pt": "Nenhuma ação de admin registrada ainda.", "tr": "Henüz yönetici işlemi kaydedilmedi.", "id": "Belum ada tindakan admin yang tercatat."},
    "trade_side_col": {"ar": "النوع", "en": "Side", "pt": "Lado", "tr": "Yön", "id": "Sisi"},
    "buyer_col": {"ar": "المشتري", "en": "Buyer", "pt": "Comprador", "tr": "Alıcı", "id": "Pembeli"},
    "seller_col": {"ar": "البائع", "en": "Seller", "pt": "Vendedor", "tr": "Satıcı", "id": "Penjual"},
    "no_trades_at_all": {"ar": "مفيش صفقات حصلت لسه.", "en": "No trades have happened yet.", "pt": "Nenhuma negociação ainda.", "tr": "Henüz hiç işlem gerçekleşmedi.", "id": "Belum ada transaksi yang terjadi."},
    "save_changes_btn": {"ar": "حفظ التعديل", "en": "Save Changes", "pt": "Salvar Alterações", "tr": "Değişiklikleri Kaydet", "id": "Simpan Perubahan"},
    "confirm_delete_stock": {"ar": "متأكد إنك عايز تحذف السهم ده نهائيًا؟ هيتشال من كل محافظ المستخدمين والأوامر المفتوحة.",
                              "en": "Are you sure you want to permanently delete this stock? It will be removed from all users' holdings and open orders.",
                              "pt": "Tem certeza que deseja excluir esta ação permanentemente? Ela será removida de todas as carteiras e ordens abertas.", "tr": "Bu hisseyi kalıcı olarak silmek istediğinizden emin misiniz? Tüm kullanıcıların varlıklarından ve açık emirlerinden kaldırılacak.", "id": "Apakah Anda yakin ingin menghapus saham ini secara permanen? Ini akan dihapus dari semua kepemilikan pengguna dan order terbuka."},
    "flash_stock_deleted": {"ar": "تم حذف السهم", "en": "Stock deleted", "pt": "Ação excluída", "tr": "Hisse silindi", "id": "Saham dihapus"},
    "delete_refund_btn": {"ar": "حذف مع استرجاع الفلوس", "en": "Delete & Refund", "pt": "Excluir e Reembolsar", "tr": "Sil ve İade Et", "id": "Hapus & Kembalikan Dana"},
    "confirm_delete_refund_stock": {"ar": "متأكد إنك عايز تحذف السهم ده وترجع لكل المساهمين فلوسهم بمتوسط السعر اللي اشتروا بيه؟ الإجراء ده مش ممكن التراجع عنه.",
                                      "en": "Are you sure you want to delete this stock and refund all shareholders at their average purchase price? This action cannot be undone.",
                                      "pt": "Tem certeza que deseja excluir esta ação e reembolsar todos os acionistas pelo preço médio de compra deles? Esta ação não pode ser desfeita.",
                                      "tr": "Bu hisseyi silmek ve tüm hissedarlara ortalama satın alma fiyatından geri ödeme yapmak istediğinizden emin misiniz? Bu işlem geri alınamaz.",
                                      "id": "Apakah Anda yakin ingin menghapus saham ini dan mengembalikan dana ke semua pemegang saham dengan harga beli rata-rata mereka? Tindakan ini tidak dapat dibatalkan."},
    "flash_stock_deleted_refunded": {"ar": "تم حذف السهم وإرجاع الفلوس لكل المساهمين", "en": "Stock deleted and all shareholders refunded", "pt": "Ação excluída e todos os acionistas reembolsados", "tr": "Hisse silindi ve tüm hissedarlara geri ödeme yapıldı", "id": "Saham dihapus dan semua pemegang saham dikembalikan dananya"},
    "confirm_password_to_delete": {"ar": "اكتب باسوردك للتأكيد", "en": "Type your password to confirm", "pt": "Digite sua senha para confirmar", "tr": "Onaylamak için şifrenizi girin", "id": "Ketik kata sandi Anda untuk konfirmasi"},
    "flash_wrong_confirm_password": {"ar": "الباسورد غلط - الحذف اتلغى", "en": "Incorrect password - deletion cancelled", "pt": "Senha incorreta - exclusão cancelada", "tr": "Yanlış şifre - silme işlemi iptal edildi", "id": "Kata sandi salah - penghapusan dibatalkan"},
    "flash_stock_updated": {"ar": "تم تعديل السهم", "en": "Stock updated", "pt": "Ação atualizada", "tr": "Hisse güncellendi", "id": "Saham diperbarui"},
    "transfers_paused_title": {"ar": "التحويل متوقف حاليًا", "en": "Transfers are currently paused", "pt": "As transferências estão pausadas no momento", "tr": "Transferler şu anda duraklatıldı", "id": "Transfer saat ini dijeda"},
    "transfers_paused_body": {"ar": "الخزنة مش متصلة دلوقتي، فالإيداع التلقائي متوقف مؤقتًا. جرب تاني بعدين أو كلم الأدمن.",
                               "en": "The vault isn't connected right now, so automatic deposits are temporarily paused. Please try again later or contact the admin.",
                               "pt": "O cofre não está conectado no momento, então os depósitos automáticos estão pausados. Tente novamente mais tarde ou contate o admin.", "tr": "Kasa şu anda bağlı değil, bu yüzden otomatik yatırmalar geçici olarak duraklatıldı. Lütfen daha sonra tekrar deneyin veya yöneticiyle iletişime geçin.", "id": "Vault saat ini tidak terhubung, sehingga setoran otomatis dijeda sementara. Silakan coba lagi nanti atau hubungi admin."},

    # flash messages
    "flash_no_telegram": {"ar": "لازم تكتب يوزر التليجرام بتاعك", "en": "You must enter your Telegram username", "pt": "Você deve informar seu usuário do Telegram", "tr": "Telegram kullanıcı adınızı girmelisiniz", "id": "Anda harus memasukkan nama pengguna Telegram Anda"},
    "flash_user_exists": {"ar": "اسم المستخدم موجود بالفعل", "en": "Username already exists", "pt": "Nome de usuário já existe", "tr": "Kullanıcı adı zaten mevcut", "id": "Nama pengguna sudah ada"},
    "flash_bad_login": {"ar": "بيانات الدخول غلط", "en": "Invalid login credentials", "pt": "Credenciais de login inválidas", "tr": "Geçersiz giriş bilgileri", "id": "Kredensial login tidak valid"},
    "flash_too_many_login_attempts": {"ar": "محاولات كتير غلط. استنى شوية وجرب تاني.", "en": "Too many failed attempts. Please wait a bit and try again.", "pt": "Muitas tentativas falhas. Aguarde um pouco e tente novamente.", "tr": "Çok fazla başarısız deneme. Lütfen biraz bekleyip tekrar deneyin.", "id": "Terlalu banyak percobaan gagal. Silakan tunggu sebentar dan coba lagi."},
    "flash_linked": {"ar": "تم ربط الحساب", "en": "Account linked", "pt": "Conta vinculada", "tr": "Hesap bağlandı", "id": "Akun tertaut"},
    "flash_no_recipient": {"ar": "مفيش حساب بالآي دي ده", "en": "No account with that ID", "pt": "Nenhuma conta com esse ID", "tr": "Bu kimlikle bir hesap yok", "id": "Tidak ada akun dengan ID tersebut"},
    "flash_self_transfer": {"ar": "مينفعش تحول لنفسك", "en": "You can't transfer to yourself", "pt": "Você não pode transferir para si mesmo", "tr": "Kendinize transfer yapamazsınız", "id": "Anda tidak dapat mentransfer ke diri sendiri"},
    "flash_insufficient": {"ar": "رصيد غير كافي", "en": "Insufficient balance", "pt": "Saldo insuficiente", "tr": "Yetersiz bakiye", "id": "Saldo tidak cukup"},
    "missing_amount_label": {"ar": "الناقص", "en": "Missing", "pt": "Faltando", "tr": "Eksik", "id": "Kurang"},
    "trading_fee_market_note": {"ar": "أي تعامل (بيع أو شراء) في السوق بياخد عمولة {fee}% على المشتري لصالح خزينة GNID.",
                                  "en": "Any transaction (buy or sell) in the market takes a {fee}% fee from the buyer for the GNID treasury.",
                                  "pt": "Qualquer transação (compra ou venda) no mercado cobra uma taxa de {fee}% do comprador para o tesouro GNID.",
                                  "tr": "Piyasadaki her işlem (alım veya satım), alıcıdan GNID hazinesi için %{fee} ücret alır.",
                                  "id": "Setiap transaksi (beli atau jual) di pasar mengenakan biaya {fee}% dari pembeli untuk kas GNID."},
    "flash_transfer_done": {"ar": "تم تحويل", "en": "Transferred", "pt": "Transferido", "tr": "Transfer edildi", "id": "Ditransfer"},
    "flash_to": {"ar": "إلى", "en": "to", "pt": "para", "tr": "-e", "id": "ke"},
    "flash_stock_saved": {"ar": "تم إضافة/تحديث السهم", "en": "Stock added/updated", "pt": "Ação adicionada/atualizada", "tr": "Hisse eklendi/güncellendi", "id": "Saham ditambahkan/diperbarui"},
    "flash_qty_unavailable": {"ar": "الكمية غير متاحة", "en": "Quantity not available", "pt": "Quantidade não disponível", "tr": "Miktar mevcut değil", "id": "Jumlah tidak tersedia"},
    "flash_bought": {"ar": "تم شراء", "en": "Bought", "pt": "Comprado", "tr": "Satın alındı", "id": "Dibeli"},
    "flash_no_qty_to_sell": {"ar": "مالكش كمية كافية من السهم عشان تبيع", "en": "You don't have enough of this stock to sell", "pt": "Você não tem quantidade suficiente para vender", "tr": "Satmak için yeterli hisseniz yok", "id": "Anda tidak memiliki cukup saham ini untuk dijual"},
    "flash_bad_order_type": {"ar": "نوع الأمر غلط", "en": "Invalid order type", "pt": "Tipo de ordem inválido", "tr": "Geçersiz emir türü", "id": "Tipe order tidak valid"},
    "flash_stock_suspended": {"ar": "التداول على الأصل ده متوقف مؤقتًا للصيانة", "en": "Trading on this asset is temporarily suspended for maintenance", "pt": "A negociação deste ativo está temporariamente suspensa para manutenção", "tr": "Bu varlıktaki işlem bakım için geçici olarak durduruldu", "id": "Perdagangan aset ini sementara ditangguhkan untuk pemeliharaan"},
    "flash_price_out_of_band": {"ar": "السعر ده بعيد جدًا عن سعر السوق الحالي. النطاق المسموح دلوقتي",
                                  "en": "This price is too far from the current market price. Allowed range right now",
                                  "pt": "Este preço está muito distante do preço de mercado atual. Faixa permitida agora",
                                  "tr": "Bu fiyat mevcut piyasa fiyatından çok uzak. Şu anda izin verilen aralık",
                                  "id": "Harga ini terlalu jauh dari harga pasar saat ini. Rentang yang diizinkan sekarang"},
    "flash_order_placed": {"ar": "تم تسجيل الأمر", "en": "Order placed", "pt": "Ordem registrada", "tr": "Emir verildi", "id": "Order dipasang"},
    "flash_duplicate_order_limit": {"ar": "عندك بالفعل نفس الأمر ده مرتين (نفس السعر والكمية) - مينفعش تحطه تاني.",
                                      "en": "You already have this exact order twice (same price and quantity) - you can't place it again.",
                                      "pt": "Você já tem essa ordem exata duas vezes (mesmo preço e quantidade) - não pode colocá-la novamente.",
                                      "tr": "Bu emri zaten iki kez verdiniz (aynı fiyat ve miktar) - tekrar veremezsiniz.",
                                      "id": "Anda sudah memiliki order yang sama persis dua kali (harga dan jumlah sama) - tidak dapat memasangnya lagi."},
    "not_authorized": {"ar": "غير مصرح", "en": "Not authorized", "pt": "Não autorizado", "tr": "Yetkiniz yok", "id": "Tidak diizinkan"},

    # deposit page
    "add_balance": {"ar": "إضافة رصيد", "en": "Add Balance", "pt": "Adicionar Saldo", "tr": "Bakiye Ekle", "id": "Tambah Saldo"},
    "deposit_title": {"ar": "إضافة رصيد من داخل اللعبة", "en": "Add Balance from In-Game", "pt": "Adicionar Saldo pelo Jogo", "tr": "Oyun İçinden Bakiye Ekle", "id": "Tambah Saldo dari Dalam Game"},
    "deposit_lede": {"ar": "اتبع الخطوات دي بالظبط عشان يضاف رصيدك تلقائيًا خلال دقيقة.",
                      "en": "Follow these steps exactly and your balance will be added automatically within a minute.",
                      "pt": "Siga esses passos exatamente e seu saldo será adicionado automaticamente em até um minuto.", "tr": "Bu adımları tam olarak izleyin, bakiyeniz bir dakika içinde otomatik olarak eklenecektir.", "id": "Ikuti langkah-langkah ini dengan tepat dan saldo Anda akan ditambahkan secara otomatis dalam waktu satu menit."},
    "deposit_step1_title": {"ar": "2. حوّل داخل اللعبة لحساب الخزنة", "en": "2. Transfer in-game to the vault account", "pt": "2. Transfira no jogo para a conta do cofre", "tr": "2. Oyun içinde kasa hesabına transfer yapın", "id": "2. Transfer dalam game ke akun vault"},
    "deposit_step1_body": {"ar": "افتح اللعبة وابعت تحويل لحساب البنك الرسمي التالي:",
                            "en": "Open the game and send a transfer to the official bank account below:",
                            "pt": "Abra o jogo e envie uma transferência para a conta oficial do banco abaixo:", "tr": "Oyunu açın ve aşağıdaki resmi banka hesabına transfer gönderin:", "id": "Buka game dan kirim transfer ke akun bank resmi di bawah ini:"},
    "vault_account_name": {"ar": "اسم الحساب داخل اللعبة", "en": "In-game account name", "pt": "Nome da conta no jogo", "tr": "Oyun içi hesap adı", "id": "Nama akun dalam game"},
    "vault_account_link": {"ar": "فتح صفحة الحساب في اللعبة", "en": "Open account in game", "pt": "Abrir conta no jogo", "tr": "Hesabı oyunda aç", "id": "Buka akun di game"},
    "vault_account_not_set": {"ar": "لسه الأدمن مضفش اسم الحساب. تقدر تستخدم الآي دي اللي تحت لغاية ما يتحدد.",
                               "en": "The admin hasn't set the account name yet. You can still use the amount below.",
                               "pt": "O admin ainda não definiu o nome da conta. Você ainda pode usar o valor abaixo.", "tr": "Yönetici henüz hesap adını ayarlamadı. Yine de aşağıdaki tutarı kullanabilirsiniz.", "id": "Admin belum mengatur nama akun. Anda tetap bisa menggunakan jumlah di bawah ini."},
    "deposit_step2_title": {"ar": "1. ابعت المبلغ الصح بالظبط", "en": "1. Send the exact right amount", "pt": "1. Envie o valor exato correto", "tr": "1. Tam doğru tutarı gönderin", "id": "1. Kirim jumlah yang tepat"},
    "deposit_step2_body": {"ar": "المبلغ لازم يكون =",
                            "en": "The amount must equal =",
                            "pt": "O valor deve ser =", "tr": "Tutar şuna eşit olmalı =", "id": "Jumlah harus sama dengan ="},
    "deposit_example": {"ar": "مثال: عايز تضيف 5000 → ابعت", "en": "Example: to add 5000 → send", "pt": "Exemplo: para adicionar 5000 → envie", "tr": "Örnek: 5000 eklemek için → gönder", "id": "Contoh: untuk menambah 5000 → kirim"},
    "deposit_worked_example_title": {"ar": "مثال محسوب بالكامل بآيديك", "en": "Full worked example with your ID", "pt": "Exemplo completo com seu ID", "tr": "Kimliğinizle tam örnek hesaplama", "id": "Contoh lengkap dengan ID Anda"},
    "desired_amount_label": {"ar": "المبلغ اللي عايز تضيفه", "en": "Amount you want to add", "pt": "Valor que você quer adicionar", "tr": "Eklemek istediğiniz tutar", "id": "Jumlah yang ingin ditambahkan"},
    "your_id_is_label": {"ar": "آيديك هو", "en": "Your ID is", "pt": "Seu ID é", "tr": "Kimliğiniz", "id": "ID Anda adalah"},
    "amount_to_send_label": {"ar": "= المبلغ اللي تبعته فعليًا", "en": "= amount to actually send", "pt": "= valor a enviar de fato", "tr": "= gerçekte gönderilecek tutar", "id": "= jumlah yang sebenarnya dikirim"},
    "deposit_step3_title": {"ar": "3. استنى شوية", "en": "3. Wait a bit", "pt": "3. Aguarde um pouco", "tr": "3. Biraz bekleyin", "id": "3. Tunggu sebentar"},
    "deposit_step3_body": {"ar": "البنك بيراقب الخزنة كل دقيقة وبيضيف رصيدك تلقائيًا لما يوصل التحويل. لو المبلغ غلط أو مش متطابق، التحويل هيتحط في مراجعة يدوية ومش هيظهر ليك غير لما الأدمن يعتمده.",
                            "en": "The bank checks the vault every minute and adds your balance automatically once the transfer arrives. If the amount is wrong, it goes to manual review and won't appear here until the admin confirms it.",
                            "pt": "O banco verifica o cofre a cada minuto e adiciona seu saldo automaticamente. Se o valor estiver errado, a transferência vai para revisão manual e só aparecerá aqui depois que o admin confirmar.", "tr": "Banka kasayı her dakika kontrol eder ve transfer ulaştığında bakiyenizi otomatik olarak ekler. Tutar yanlışsa, manuel incelemeye gider ve yönetici onaylayana kadar burada görünmez.", "id": "Bank memeriksa vault setiap menit dan menambahkan saldo Anda secara otomatis setelah transfer tiba. Jika jumlahnya salah, akan masuk tinjauan manual dan tidak akan muncul di sini sampai admin mengonfirmasinya."},
    "deposit_history": {"ar": "سجل الإيداعات المؤكدة", "en": "Confirmed Deposit History", "pt": "Histórico de Depósitos Confirmados", "tr": "Onaylanmış Yatırma Geçmişi", "id": "Riwayat Setoran Terkonfirmasi"},
    "date_col": {"ar": "التاريخ", "en": "Date", "pt": "Data", "tr": "Tarih", "id": "Tanggal"},
    "credited_col": {"ar": "المضاف للرصيد", "en": "Credited", "pt": "Creditado", "tr": "Yatırılan", "id": "Dikreditkan"},
    "no_deposits_yet": {"ar": "مفيش إيداعات مؤكدة لسه.", "en": "No confirmed deposits yet.", "pt": "Nenhum depósito confirmado ainda.", "tr": "Henüz onaylanmış yatırma yok.", "id": "Belum ada setoran terkonfirmasi."},
}

TR.update({
    # balance chip
    "id_label": {"ar": "آي دي", "en": "ID", "pt": "ID", "tr": "Kimlik", "id": "ID"},
    "balance_word_cap": {"ar": "رصيد", "en": "Balance", "pt": "Saldo", "tr": "Bakiye", "id": "Saldo"},

    # admin vault settings panel
    "admin_vault_title": {"ar": "إعدادات الخزنة (الإيداع التلقائي من اللعبة)",
                           "en": "Vault Settings (Automatic In-Game Deposits)",
                           "pt": "Configurações do Cofre (Depósitos Automáticos)", "tr": "Kasa Ayarları (Otomatik Oyun İçi Yatırmalar)", "id": "Pengaturan Vault (Setoran Otomatis Dalam Game)"},
    "admin_vault_id_range": {"ar": "مدى آي دي الحسابات الحالي: من 1 لغاية",
                              "en": "Current account ID range: 1 to",
                              "pt": "Faixa atual de IDs de conta: 1 até", "tr": "Mevcut hesap kimlik aralığı: 1 ile", "id": "Rentang ID akun saat ini: 1 sampai"},
    "admin_vault_example": {"ar": 'يعني لو مستخدم عايز يضيف رصيد "5000" وآي دي حسابه "482"، المبلغ اللي يرسله جوه اللعبة للخزنة = 5000 + 482 = 5482.',
                             "en": 'So if a user wants to add "5000" and their account ID is "482", the amount they send in-game to the vault = 5000 + 482 = 5482.',
                             "pt": 'Se um usuário quer adicionar "5000" e o ID da conta é "482", o valor enviado no jogo para o cofre = 5000 + 482 = 5482.', "tr": "Yani bir kullanıcı \"5000\" eklemek istiyorsa ve hesap kimliği \"482\" ise, oyun içinde kasaya göndereceği tutar = 5000 + 482 = 5482.", "id": "Jadi jika pengguna ingin menambah \"5000\" dan ID akunnya \"482\", jumlah yang dikirim dalam game ke vault = 5000 + 482 = 5482."},
    "admin_vault_credited_note": {"ar": "الرصيد اللي بيتضاف = المبلغ المرسل ناقص آي دي الحساب.",
                                   "en": "Amount credited = amount sent minus the account ID.",
                                   "pt": "Valor creditado = valor enviado menos o ID da conta.", "tr": "Yatırılan tutar = gönderilen tutar eksi hesap kimliği.", "id": "Jumlah yang dikreditkan = jumlah yang dikirim dikurangi ID akun."},
    "vault_token_label": {"ar": "توكن حساب الخزنة (Bearer token)", "en": "Vault account token (Bearer token)", "pt": "Token da conta do cofre (Bearer token)", "tr": "Kasa hesap tokenı (Bearer token)", "id": "Token akun vault (Bearer token)"},
    "vault_token_placeholder": {"ar": "التوكن هنا", "en": "Token here", "pt": "Token aqui", "tr": "Token buraya", "id": "Token di sini"},
    "vault_player_id_label": {"ar": "آي دي حساب الخزنة داخل اللعبة (اختياري - للعرض بس)", "en": "Vault's in-game account ID (optional - display only)", "pt": "ID da conta do cofre no jogo (opcional - só exibição)", "tr": "Kasanın oyun içi hesap kimliği (isteğe bağlı - sadece görüntüleme)", "id": "ID akun dalam game vault (opsional - hanya tampilan)"},
    "vault_account_name_label": {"ar": "اسم حساب الخزنة داخل اللعبة (بيظهر للمستخدمين في صفحة الإيداع)", "en": "Vault's in-game account name (shown to users on the deposit page)", "pt": "Nome da conta do cofre no jogo (exibido na página de depósito)", "tr": "Kasanın oyun içi hesap adı (yatırma sayfasında kullanıcılara gösterilir)", "id": "Nama akun dalam game vault (ditampilkan kepada pengguna di halaman setoran)"},
    "vault_account_url_label": {"ar": "رابط صفحة الحساب داخل اللعبة (اختياري)", "en": "Link to the account page in-game (optional)", "pt": "Link da página da conta no jogo (opcional)", "tr": "Oyun içi hesap sayfasına bağlantı (isteğe bağlı)", "id": "Tautan ke halaman akun dalam game (opsional)"},
    "save_vault_settings_btn": {"ar": "حفظ إعدادات الخزنة", "en": "Save Vault Settings", "pt": "Salvar Configurações do Cofre", "tr": "Kasa Ayarlarını Kaydet", "id": "Simpan Pengaturan Vault"},
    "vault_status_label": {"ar": "الحالة", "en": "Status", "pt": "Status", "tr": "Durum", "id": "Status"},
    "vault_connected": {"ar": "متصلة ✅", "en": "Connected ✅", "pt": "Conectado ✅", "tr": "Bağlı ✅", "id": "Terhubung ✅"},
    "vault_disconnected": {"ar": "متوقفة ⚠️", "en": "Disconnected ⚠️", "pt": "Desconectado ⚠️", "tr": "Bağlı Değil ⚠️", "id": "Terputus ⚠️"},
    "vault_last_balance_label": {"ar": "آخر رصيد محفوظ", "en": "Last saved balance", "pt": "Último saldo salvo", "tr": "Son kaydedilen bakiye", "id": "Saldo terakhir tersimpan"},
    "vault_last_update_label": {"ar": "آخر تحديث", "en": "Last updated", "pt": "Última atualização", "tr": "Son güncelleme", "id": "Terakhir diperbarui"},

    # confirmed deposits log
    "confirmed_deposits_title": {"ar": "سجل الإيداعات المؤكدة", "en": "Confirmed Deposits Log", "pt": "Histórico de Depósitos Confirmados", "tr": "Onaylanmış Yatırmalar Günlüğü", "id": "Log Setoran Terkonfirmasi"},
    "pending_deposits_title": {"ar": "إيداعات محتاجة مراجعة يدوية", "en": "Deposits Needing Manual Review", "pt": "Depósitos Precisando de Revisão Manual", "tr": "Manuel İnceleme Gereken Yatırmalar", "id": "Setoran yang Perlu Tinjauan Manual"},
    "pending_deposits_lede": {"ar": "المبلغ ده وصل للخزنة لكن النظام مقدرش يحدد صاحبه تلقائيًا (مثلاً لو حصل تحويلين في نفس الوقت أو المبلغ زاد عن الحد الأقصى القديم). حط آي دي صاحب المبلغ وقيمة الإيداع الصح واضغط اعتماد، أو تجاهل لو مش لازم.",
                                "en": "This amount reached the vault but the system couldn't auto-match it to a user (e.g. two transfers at once, or it exceeded the old max limit). Enter the correct account ID and amount, then approve — or ignore if not needed.",
                                "pt": "Esse valor chegou ao cofre mas o sistema não conseguiu identificar o dono automaticamente. Insira o ID da conta correta e o valor, depois aprove — ou ignore se não for necessário.", "tr": "Bu tutar kasaya ulaştı ancak sistem bunu otomatik olarak bir kullanıcıyla eşleştiremedi (örneğin aynı anda iki transfer, veya eski maksimum limiti aştı). Doğru hesap kimliğini ve tutarı girin, ardından onaylayın — veya gerekli değilse yok sayın.", "id": "Jumlah ini sampai ke vault tetapi sistem tidak dapat mencocokkannya secara otomatis dengan pengguna (misalnya dua transfer sekaligus, atau melebihi batas maksimum lama). Masukkan ID akun dan jumlah yang benar, lalu setujui — atau abaikan jika tidak diperlukan."},
    "delta_col": {"ar": "المبلغ المرسل الكامل", "en": "Raw Amount Sent", "pt": "Valor Bruto Enviado", "tr": "Gönderilen Ham Tutar", "id": "Jumlah Mentah Terkirim"},
    "ignore_deposit_btn": {"ar": "تجاهل", "en": "Ignore", "pt": "Ignorar", "tr": "Yok Say", "id": "Abaikan"},
    "flash_deposit_ignored": {"ar": "تم تجاهل الإيداع", "en": "Deposit ignored", "pt": "Depósito ignorado", "tr": "Yatırma yok sayıldı", "id": "Setoran diabaikan"},

    # admin users page
    "manage_users_title": {"ar": "إدارة المستخدمين", "en": "Manage Users", "pt": "Gerenciar Usuários", "tr": "Kullanıcıları Yönet", "id": "Kelola Pengguna"},
    "manage_users_lede": {"ar": "كل الحسابات المسجلة في البنك — تقدر تحذف أي حساب من هنا.",
                           "en": "All registered bank accounts — you can delete any account from here.",
                           "pt": "Todas as contas registradas no banco — você pode excluir qualquer conta aqui.", "tr": "Tüm kayıtlı banka hesapları — herhangi bir hesabı buradan silebilirsiniz.", "id": "Semua akun bank terdaftar — Anda dapat menghapus akun mana pun dari sini."},
    "search_users_placeholder": {"ar": "🔍 ابحث بالاسم أو يوزر التليجرام أو الآيدي...",
                                   "en": "🔍 Search by username, Telegram, or ID...",
                                   "pt": "🔍 Buscar por usuário, Telegram ou ID...",
                                   "tr": "🔍 Kullanıcı adı, Telegram veya ID ile ara...",
                                   "id": "🔍 Cari berdasarkan nama pengguna, Telegram, atau ID..."},
    "no_search_results": {"ar": "مفيش نتايج مطابقة للبحث.", "en": "No results match your search.",
                            "pt": "Nenhum resultado corresponde à sua busca.", "tr": "Aramanızla eşleşen sonuç yok.",
                            "id": "Tidak ada hasil yang cocok dengan pencarian Anda."},
    "balance_col": {"ar": "الرصيد", "en": "Balance", "pt": "Saldo", "tr": "Bakiye", "id": "Saldo"},
    "is_admin_col": {"ar": "أدمن؟", "en": "Admin?", "pt": "Admin?", "tr": "Yönetici mi?", "id": "Admin?"},
    "frozen_col": {"ar": "مجمّد؟", "en": "Frozen?", "pt": "Congelado?", "tr": "Donduruldu mu?", "id": "Dibekukan?"},
    "frozen_word": {"ar": "مجمّد", "en": "Frozen", "pt": "Congelado", "tr": "Donduruldu", "id": "Dibekukan"},
    "unfreeze_btn": {"ar": "فك التجميد", "en": "Unfreeze", "pt": "Descongelar", "tr": "Dondurmayı Kaldır", "id": "Cairkan"},
    "flash_user_unfrozen": {"ar": "تم فك التجميد عن الحساب", "en": "Account unfrozen", "pt": "Conta descongelada", "tr": "Hesap dondurması kaldırıldı", "id": "Akun dicairkan"},
    "yes_word": {"ar": "نعم", "en": "Yes", "pt": "Sim", "tr": "Evet", "id": "Ya"},
    "no_word": {"ar": "لا", "en": "No", "pt": "Não", "tr": "Hayır", "id": "Tidak"},
    "confirm_delete_user": {"ar": "متأكد إنك عايز تحذف الحساب ده نهائيًا؟ الأسهم والأوامر المرتبطة بيه هتتحذف كمان.",
                             "en": "Are you sure you want to permanently delete this account? Its stocks and orders will be deleted too.",
                             "pt": "Tem certeza que deseja excluir permanentemente esta conta? As ações e ordens dela também serão excluídas.", "tr": "Bu hesabı kalıcı olarak silmek istediğinizden emin misiniz? Hisseleri ve emirleri de silinecek.", "id": "Apakah Anda yakin ingin menghapus akun ini secara permanen? Saham dan order-nya juga akan dihapus."},
    "delete_account_btn": {"ar": "حذف الحساب", "en": "Delete Account", "pt": "Excluir Conta", "tr": "Hesabı Sil", "id": "Hapus Akun"},
    "your_account_label": {"ar": "(حسابك)", "en": "(your account)", "pt": "(sua conta)", "tr": "(hesabınız)", "id": "(akun Anda)"},
    "no_users_yet": {"ar": "مفيش مستخدمين مسجلين لسه.", "en": "No registered users yet.", "pt": "Nenhum usuário registrado ainda.", "tr": "Henüz kayıtlı kullanıcı yok.", "id": "Belum ada pengguna terdaftar."},
    "adjust_balance_btn": {"ar": "تعديل الرصيد", "en": "Adjust Balance", "pt": "Ajustar Saldo", "tr": "Bakiyeyi Ayarla", "id": "Sesuaikan Saldo"},
    "change_password_btn": {"ar": "تغيير الباسورد", "en": "Change Password", "pt": "Alterar Senha", "tr": "Şifre Değiştir", "id": "Ubah Kata Sandi"},
    "add_word": {"ar": "إضافة", "en": "Add", "pt": "Adicionar", "tr": "Ekle", "id": "Tambah"},
    "subtract_word": {"ar": "خصم", "en": "Subtract", "pt": "Subtrair", "tr": "Çıkar", "id": "Kurangi"},
    "apply_btn": {"ar": "تنفيذ", "en": "Apply", "pt": "Aplicar", "tr": "Uygula", "id": "Terapkan"},
    "new_password_placeholder": {"ar": "الباسورد الجديد", "en": "New password", "pt": "Nova senha", "tr": "Yeni şifre", "id": "Kata sandi baru"},
    "save_password_btn": {"ar": "حفظ الباسورد", "en": "Save Password", "pt": "Salvar Senha", "tr": "Şifreyi Kaydet", "id": "Simpan Kata Sandi"},
    "flash_balance_adjusted": {"ar": "تم تعديل الرصيد", "en": "Balance adjusted", "pt": "Saldo ajustado", "tr": "Bakiye ayarlandı", "id": "Saldo disesuaikan"},
    "flash_password_changed": {"ar": "تم تغيير الباسورد", "en": "Password changed", "pt": "Senha alterada", "tr": "Şifre değiştirildi", "id": "Kata sandi diubah"},
    "flash_bad_amount": {"ar": "المبلغ غير صحيح", "en": "Invalid amount", "pt": "Valor inválido", "tr": "Geçersiz tutar", "id": "Jumlah tidak valid"},
    "flash_ownership_over_100": {"ar": "نسبة المالك + GNID متعديتش الـ 100%", "en": "Owner % + GNID % can't exceed 100%", "pt": "% do proprietário + % da GNID não pode exceder 100%", "tr": "Sahip % + GNID % 100%'ü geçemez", "id": "% Pemilik + % GNID tidak boleh melebihi 100%"},
    "flash_insufficient_target": {"ar": "الرصيد مش كفاية عشان تخصم المبلغ ده", "en": "Balance isn't enough to subtract that amount", "pt": "Saldo insuficiente para subtrair esse valor", "tr": "Bu tutarı çıkarmak için bakiye yeterli değil", "id": "Saldo tidak cukup untuk mengurangi jumlah tersebut"},

    # investment
    "investment": {"ar": "استثمار", "en": "Investment", "pt": "Investimento", "tr": "Yatırım", "id": "Investasi"},
    "investment_title": {"ar": "الاستثمار التلقائي", "en": "Automatic Investment", "pt": "Investimento Automático", "tr": "Otomatik Yatırım", "id": "Investasi Otomatis"},
    "investment_lede": {"ar": "ودّع مبلغ من رصيدك وخده تاني تلقائيًا بعد المدة المحددة مع نسبة أرباح ثابتة — من غير أي تدخل من الأدمن.",
                         "en": "Deposit part of your balance and get it back automatically after the fixed term, plus a fixed profit rate — no admin involvement needed.",
                         "pt": "Deposite parte do seu saldo e receba de volta automaticamente após o prazo, com uma taxa de lucro fixa — sem precisar de admin.", "tr": "Bakiyenizin bir kısmını yatırın ve sabit süre sonunda sabit bir kâr oranıyla birlikte otomatik olarak geri alın — yönetici müdahalesi gerekmez.", "id": "Setorkan sebagian saldo Anda dan dapatkan kembali secara otomatis setelah jangka waktu tetap, ditambah tingkat keuntungan tetap — tanpa perlu keterlibatan admin."},
    "investment_terms": {"ar": "المدة", "en": "Term", "pt": "Prazo", "tr": "Süre", "id": "Jangka Waktu"},
    "investment_rate": {"ar": "نسبة الربح", "en": "Profit rate", "pt": "Taxa de lucro", "tr": "Kâr oranı", "id": "Tingkat keuntungan"},
    "investment_min": {"ar": "أقل مبلغ للاستثمار", "en": "Minimum investment", "pt": "Investimento mínimo", "tr": "Minimum yatırım", "id": "Investasi minimum"},

    # company registration (player-owned companies as tradable stocks)
    "company_apply_title": {"ar": "تسجيل شركة جديدة", "en": "Register a Company", "pt": "Registrar uma Empresa", "tr": "Şirket Kaydet", "id": "Daftarkan Perusahaan"},
    "company_apply_lede": {"ar": "لو عندك مصنع أو شركة جوه اللعبة وعايز تحولها لسهم متداول في السوق، ابعت بياناتها هنا. الأدمن هيراجع الطلب ويوافق أو يرفض.",
                             "en": "If you have a factory or company in-game and want to turn it into a tradable stock in the market, submit its details here. An admin will review and approve or reject the request.",
                             "pt": "Se você tem uma fábrica ou empresa no jogo e quer transformá-la em uma ação negociável no mercado, envie os detalhes aqui. Um admin vai revisar e aprovar ou rejeitar a solicitação.",
                             "tr": "Oyun içinde bir fabrikanız veya şirketiniz varsa ve onu piyasada işlem gören bir hisseye dönüştürmek istiyorsanız, bilgilerini buradan gönderin. Bir yönetici talebi inceleyip onaylayacak veya reddedecektir.",
                             "id": "Jika Anda memiliki pabrik atau perusahaan dalam game dan ingin mengubahnya menjadi saham yang dapat diperdagangkan di pasar, kirimkan detailnya di sini. Admin akan meninjau dan menyetujui atau menolak permintaan tersebut."},
    "company_owner_share_label": {"ar": "نصيبك انت (المالك)", "en": "Your Share (Owner)", "pt": "Sua Parte (Dono)", "tr": "Payınız (Sahip)", "id": "Bagian Anda (Pemilik)"},
    "company_gnid_share_label": {"ar": "نصيب خزينة GNID", "en": "GNID Treasury Share", "pt": "Parte do Tesouro GNID", "tr": "GNID Hazine Payı", "id": "Bagian Kas GNID"},
    "company_market_share_label": {"ar": "المتاح للطرح العام فورًا", "en": "Available for Immediate Public Offering", "pt": "Disponível para Oferta Pública Imediata", "tr": "Anında Halka Arz için Uygun", "id": "Tersedia untuk Penawaran Publik Segera"},
    "company_name_label": {"ar": "اسم الشركة", "en": "Company Name", "pt": "Nome da Empresa", "tr": "Şirket Adı", "id": "Nama Perusahaan"},
    "company_symbol_label": {"ar": "رمز الشركة (Symbol)", "en": "Company Symbol", "pt": "Símbolo da Empresa", "tr": "Şirket Sembolü", "id": "Simbol Perusahaan"},
    "factory_link_label": {"ar": "رابط المصنع/الشركة داخل اللعبة", "en": "In-game Factory/Company Link", "pt": "Link da Fábrica/Empresa no Jogo", "tr": "Oyun İçi Fabrika/Şirket Bağlantısı", "id": "Tautan Pabrik/Perusahaan dalam Game"},
    "company_level_label": {"ar": "مستوى الشركة", "en": "Company Level", "pt": "Nível da Empresa", "tr": "Şirket Seviyesi", "id": "Level Perusahaan"},
    "company_capital_label": {"ar": "رأس المال الحالي (الكاش)", "en": "Current Capital (Cash)", "pt": "Capital Atual (Caixa)", "tr": "Mevcut Sermaye (Nakit)", "id": "Modal Saat Ini (Kas)"},
    "company_daily_production_label": {"ar": "الإنتاج اليومي", "en": "Daily Production", "pt": "Produção Diária", "tr": "Günlük Üretim", "id": "Produksi Harian"},
    "company_apply_btn": {"ar": "إرسال طلب التسجيل", "en": "Submit Registration Request", "pt": "Enviar Solicitação de Registro", "tr": "Kayıt Talebi Gönder", "id": "Kirim Permintaan Pendaftaran"},
    "my_company_requests": {"ar": "طلباتي", "en": "My Requests", "pt": "Minhas Solicitações", "tr": "Taleplerim", "id": "Permintaan Saya"},
    "no_company_requests_yet": {"ar": "لسه معملتش أي طلب تسجيل شركة.", "en": "You haven't made any company registration requests yet.", "pt": "Você ainda não fez nenhuma solicitação de registro de empresa.", "tr": "Henüz hiç şirket kayıt talebi göndermediniz.", "id": "Anda belum membuat permintaan pendaftaran perusahaan apa pun."},
    "valuation_col": {"ar": "التقييم", "en": "Valuation", "pt": "Avaliação", "tr": "Değerleme", "id": "Valuasi"},
    "view_company_btn": {"ar": "عرض الشركة", "en": "View Company", "pt": "Ver Empresa", "tr": "Şirketi Görüntüle", "id": "Lihat Perusahaan"},
    "admin_companies_title": {"ar": "طلبات تسجيل الشركات", "en": "Company Registration Requests", "pt": "Solicitações de Registro de Empresa", "tr": "Şirket Kayıt Talepleri", "id": "Permintaan Pendaftaran Perusahaan"},
    "admin_companies_lede": {"ar": "طلبات المستخدمين لتسجيل مصانعهم/شركاتهم كأسهم متداولة. الموافقة بتنشئ سهم جديد تلقائيًا بالتقسيم: 50% مالك / 10% GNID / 40% سوق.",
                               "en": "User requests to register their factories/companies as tradable stocks. Approving creates a new stock automatically with the split: 50% owner / 10% GNID / 40% market.",
                               "pt": "Solicitações de usuários para registrar suas fábricas/empresas como ações negociáveis. Aprovar cria uma nova ação automaticamente com a divisão: 50% dono / 10% GNID / 40% mercado.",
                               "tr": "Kullanıcıların fabrikalarını/şirketlerini işlem gören hisseler olarak kaydettirme talepleri. Onaylamak otomatik olarak şu dağılımla yeni bir hisse oluşturur: %50 sahip / %10 GNID / %40 piyasa.",
                               "id": "Permintaan pengguna untuk mendaftarkan pabrik/perusahaan mereka sebagai saham yang dapat diperdagangkan. Menyetujui akan otomatis membuat saham baru dengan pembagian: 50% pemilik / 10% GNID / 40% pasar."},
    "view_link_word": {"ar": "عرض الرابط", "en": "View Link", "pt": "Ver Link", "tr": "Bağlantıyı Görüntüle", "id": "Lihat Tautan"},
    "reject_reason_placeholder": {"ar": "سبب الرفض (اختياري)", "en": "Reason (optional)", "pt": "Motivo (opcional)", "tr": "Sebep (isteğe bağlı)", "id": "Alasan (opsional)"},
    "flash_company_request_sent": {"ar": "تم إرسال طلب تسجيل الشركة، هيتراجع من الأدمن قريبًا", "en": "Company registration request sent, an admin will review it soon", "pt": "Solicitação de registro da empresa enviada, um admin vai revisá-la em breve", "tr": "Şirket kayıt talebi gönderildi, bir yönetici yakında inceleyecek", "id": "Permintaan pendaftaran perusahaan terkirim, admin akan segera meninjaunya"},
    "flash_company_link_already_used": {"ar": "رابط المصنع/الشركة ده مسجّل بالفعل (معلق أو موافق عليه) - مش ممكن تسجيله مرة تانية.",
                                          "en": "This factory/company link is already registered (pending or approved) - it can't be submitted again.",
                                          "pt": "Este link de fábrica/empresa já está registrado (pendente ou aprovado) - não pode ser enviado novamente.",
                                          "tr": "Bu fabrika/şirket bağlantısı zaten kayıtlı (beklemede veya onaylanmış) - tekrar gönderilemez.",
                                          "id": "Tautan pabrik/perusahaan ini sudah terdaftar (menunggu atau disetujui) - tidak dapat dikirim lagi."},
    "flash_company_approved": {"ar": "تم قبول الطلب وإنشاء السهم بنجاح", "en": "Request approved and stock created successfully", "pt": "Solicitação aprovada e ação criada com sucesso", "tr": "Talep onaylandı ve hisse başarıyla oluşturuldu", "id": "Permintaan disetujui dan saham berhasil dibuat"},
    "flash_company_rejected": {"ar": "تم رفض الطلب", "en": "Request rejected", "pt": "Solicitação rejeitada", "tr": "Talep reddedildi", "id": "Permintaan ditolak"},
    "nav_currency_apply": {"ar": "أصدر عملتك", "en": "Issue Your Currency", "pt": "Emitir Sua Moeda", "tr": "Kendi Paranızı Çıkarın", "id": "Terbitkan Mata Uang Anda"},
    "nav_admin_currencies": {"ar": "طلبات العملات", "en": "Currency Requests", "pt": "Solicitações de Moeda", "tr": "Para Talepleri", "id": "Permintaan Mata Uang"},
    "currency_apply_title": {"ar": "إصدار عملة خاصة", "en": "Issue a Private Currency", "pt": "Emitir uma Moeda Privada", "tr": "Özel Para Birimi Çıkar", "id": "Terbitkan Mata Uang Pribadi"},
    "currency_apply_lede": {"ar": "عايز تصدر عملتك الخاصة وتتداولها في السوق؟ ابعت تقرير عنها هنا. هنراجع طلبك وبروفايلك، ولو اتوافق هنعمل عقد ونطلق العملة. تبدأ بـ100% من إجمالي الوحدات ملكك، وكل أسبوع (يوم الجمعة) بتوزع إيرادك: 40% ليك، 10% لأكبر 5 حاملين للعملة، و50% لخزينة GNID.",
                              "en": "Want to issue your own currency and trade it on the market? Send us a report about it here. We'll review your request and profile, and if approved we'll draw up a contract and launch the currency. You start owning 100% of the total units, and every week (Friday) revenue is split: 40% to you, 10% to the top 5 currency holders, and 50% to the GNID treasury.",
                              "pt": "Quer emitir sua própria moeda e negociá-la no mercado? Envie um relatório sobre ela aqui. Vamos analisar sua solicitação e perfil, e se aprovado faremos um contrato e lançaremos a moeda. Você começa com 100% do total de unidades, e toda semana (sexta-feira) a receita é dividida: 40% para você, 10% para os 5 maiores detentores da moeda, e 50% para o tesouro do GNID.",
                              "tr": "Kendi para biriminizi çıkarıp piyasada işlem görmesini mi istiyorsunuz? Buradan hakkında bir rapor gönderin. Talebinizi ve profilinizi inceleyeceğiz, onaylanırsa bir sözleşme hazırlayıp parayı piyasaya süreceğiz. Toplam birimlerin %100'üne sahip olarak başlarsınız ve her hafta (Cuma) gelir şöyle paylaştırılır: %40 size, %10 en büyük 5 para sahibine, %50 GNID hazinesine.",
                              "id": "Ingin menerbitkan mata uang Anda sendiri dan memperdagangkannya di pasar? Kirimkan laporan tentangnya di sini. Kami akan meninjau permintaan dan profil Anda, dan jika disetujui kami akan membuat kontrak dan meluncurkan mata uang tersebut. Anda mulai dengan memiliki 100% dari total unit, dan setiap minggu (Jumat) pendapatan dibagi: 40% untuk Anda, 10% untuk 5 pemegang mata uang terbesar, dan 50% untuk kas GNID."},
    "currency_name_label": {"ar": "اسم العملة", "en": "Currency Name", "pt": "Nome da Moeda", "tr": "Para Birimi Adı", "id": "Nama Mata Uang"},
    "currency_symbol_label": {"ar": "رمز العملة (Symbol)", "en": "Currency Symbol", "pt": "Símbolo da Moeda", "tr": "Para Birimi Sembolü", "id": "Simbol Mata Uang"},
    "currency_report_label": {"ar": "تقرير عن العملة (الغرض منها، السند الاقتصادي، إلخ)", "en": "Report about the currency (purpose, economic backing, etc.)", "pt": "Relatório sobre a moeda (propósito, lastro econômico, etc.)", "tr": "Para birimi hakkında rapor (amacı, ekonomik dayanağı vb.)", "id": "Laporan tentang mata uang (tujuan, dukungan ekonomi, dll.)"},
    "currency_apply_btn": {"ar": "إرسال طلب الإصدار", "en": "Submit Issuance Request", "pt": "Enviar Solicitação de Emissão", "tr": "Çıkarma Talebi Gönder", "id": "Kirim Permintaan Penerbitan"},
    "my_currency_requests": {"ar": "طلباتي", "en": "My Requests", "pt": "Minhas Solicitações", "tr": "Taleplerim", "id": "Permintaan Saya"},
    "no_currency_requests_yet": {"ar": "لسه معملتش أي طلب إصدار عملة.", "en": "You haven't made any currency issuance requests yet.", "pt": "Você ainda não fez nenhuma solicitação de emissão de moeda.", "tr": "Henüz hiç para çıkarma talebi göndermediniz.", "id": "Anda belum membuat permintaan penerbitan mata uang apa pun."},
    "view_currency_btn": {"ar": "عرض العملة", "en": "View Currency", "pt": "Ver Moeda", "tr": "Para Birimini Görüntüle", "id": "Lihat Mata Uang"},
    "admin_currencies_title": {"ar": "طلبات إصدار العملات", "en": "Currency Issuance Requests", "pt": "Solicitações de Emissão de Moeda", "tr": "Para Çıkarma Talepleri", "id": "Permintaan Penerbitan Mata Uang"},
    "admin_currencies_lede": {"ar": "طلبات المستخدمين لإصدار عملاتهم الخاصة كأصول متداولة. الموافقة بتنشئ سهم/عملة جديدة وكل الوحدات تروح 100% لصاحب الطلب.",
                                "en": "User requests to issue their own currencies as tradable assets. Approving creates a new currency and all units go 100% to the requester.",
                                "pt": "Solicitações de usuários para emitir suas próprias moedas como ativos negociáveis. Aprovar cria uma nova moeda e todas as unidades vão 100% para o solicitante.",
                                "tr": "Kullanıcıların kendi para birimlerini işlem gören varlıklar olarak çıkarma talepleri. Onaylamak yeni bir para birimi oluşturur ve tüm birimler %100 talep sahibine gider.",
                                "id": "Permintaan pengguna untuk menerbitkan mata uang mereka sendiri sebagai aset yang dapat diperdagangkan. Menyetujui akan membuat mata uang baru dan semua unit 100% menjadi milik pemohon."},
    "currency_report_col": {"ar": "التقرير", "en": "Report", "pt": "Relatório", "tr": "Rapor", "id": "Laporan"},
    "flash_currency_request_sent": {"ar": "تم إرسال طلب إصدار العملة، هيتراجع من الأدمن قريبًا", "en": "Currency issuance request sent, an admin will review it soon", "pt": "Solicitação de emissão de moeda enviada, um admin vai revisá-la em breve", "tr": "Para çıkarma talebi gönderildi, bir yönetici yakında inceleyecek", "id": "Permintaan penerbitan mata uang terkirim, admin akan segera meninjaunya"},
    "currency_initial_price_label": {"ar": "سعر الوحدة عند الإصدار", "en": "Unit Price at Issuance", "pt": "Preço da Unidade na Emissão", "tr": "Çıkarılışta Birim Fiyatı", "id": "Harga Unit saat Penerbitan"},
    "currency_total_supply_label": {"ar": "إجمالي عدد الوحدات", "en": "Total Number of Units", "pt": "Número Total de Unidades", "tr": "Toplam Birim Sayısı", "id": "Jumlah Total Unit"},
    "flash_currency_approved": {"ar": "تم قبول الطلب وإصدار العملة بنجاح - كل الوحدات دلوقتي ملك صاحب الطلب", "en": "Request approved and currency issued successfully - all units now belong to the requester", "pt": "Solicitação aprovada e moeda emitida com sucesso - todas as unidades agora pertencem ao solicitante", "tr": "Talep onaylandı ve para birimi başarıyla çıkarıldı - tüm birimler artık talep sahibine ait", "id": "Permintaan disetujui dan mata uang berhasil diterbitkan - semua unit sekarang milik pemohon"},
    "flash_currency_rejected": {"ar": "تم رفض الطلب", "en": "Request rejected", "pt": "Solicitação rejeitada", "tr": "Talep reddedildi", "id": "Permintaan ditolak"},
    "currency_revenue_label": {"ar": "الإيراد الأسبوعي", "en": "Weekly Revenue", "pt": "Receita Semanal", "tr": "Haftalık Gelir", "id": "Pendapatan Mingguan"},
    "distribute_revenue_btn": {"ar": "وزّع الإيراد", "en": "Distribute Revenue", "pt": "Distribuir Receita", "tr": "Geliri Dağıt", "id": "Distribusikan Pendapatan"},
    "confirm_distribute_revenue": {"ar": "متأكد إنك عايز توزع الإيراد ده؟", "en": "Are you sure you want to distribute this revenue?", "pt": "Tem certeza que deseja distribuir esta receita?", "tr": "Bu geliri dağıtmak istediğinizden emin misiniz?", "id": "Yakin ingin mendistribusikan pendapatan ini?"},
    "flash_currency_revenue_distributed": {"ar": "تم توزيع الإيراد بنجاح: 40% للمالك، 10% لأكبر 5 حاملين، 50% لخزينة GNID", "en": "Revenue distributed successfully: 40% to owner, 10% to top 5 holders, 50% to GNID treasury", "pt": "Receita distribuída com sucesso: 40% para o dono, 10% para os 5 maiores detentores, 50% para o tesouro GNID", "tr": "Gelir başarıyla dağıtıldı: %40 sahibine, %10 en büyük 5 sahibine, %50 GNID hazinesine", "id": "Pendapatan berhasil didistribusikan: 40% untuk pemilik, 10% untuk 5 pemegang terbesar, 50% untuk kas GNID"},
    "flash_no_currency_owner": {"ar": "مفيش مالك مسجل للعملة دي", "en": "No registered owner for this currency", "pt": "Nenhum dono registrado para esta moeda", "tr": "Bu para biriminin kayıtlı bir sahibi yok", "id": "Tidak ada pemilik terdaftar untuk mata uang ini"},
    "suspend_btn": {"ar": "إيقاف مؤقت", "en": "Suspend", "pt": "Suspender", "tr": "Askıya Al", "id": "Tangguhkan"},
    "resume_btn": {"ar": "استئناف التداول", "en": "Resume Trading", "pt": "Retomar Negociação", "tr": "İşlemi Devam Ettir", "id": "Lanjutkan Perdagangan"},
    "flash_stock_now_suspended": {"ar": "تم إيقاف التداول مؤقتًا", "en": "Trading has been suspended", "pt": "A negociação foi suspensa", "tr": "İşlem askıya alındı", "id": "Perdagangan telah ditangguhkan"},
    "flash_stock_now_resumed": {"ar": "تم استئناف التداول", "en": "Trading has been resumed", "pt": "A negociação foi retomada", "tr": "İşlem yeniden başlatıldı", "id": "Perdagangan telah dilanjutkan"},
    "currencies_section_title": {"ar": "العملات الخاصة", "en": "Private Currencies", "pt": "Moedas Privadas", "tr": "Özel Para Birimleri", "id": "Mata Uang Pribadi"},
    "currency_owner_label": {"ar": "المالك", "en": "Owner", "pt": "Dono", "tr": "Sahibi", "id": "Pemilik"},
    "no_live_currencies": {"ar": "لسه مفيش عملات اتوافق عليها.", "en": "No currencies have been approved yet.", "pt": "Nenhuma moeda foi aprovada ainda.", "tr": "Henüz onaylanmış bir para birimi yok.", "id": "Belum ada mata uang yang disetujui."},
    "suspended_badge": {"ar": "⏸️ متوقف مؤقتًا", "en": "⏸️ Suspended", "pt": "⏸️ Suspenso", "tr": "⏸️ Askıya Alındı", "id": "⏸️ Ditangguhkan"},
    "action_currency_approve": {"ar": "قبول طلب عملة", "en": "Currency Approved", "pt": "Moeda Aprovada", "tr": "Para Birimi Onaylandı", "id": "Mata Uang Disetujui"},
    "action_currency_reject": {"ar": "رفض طلب عملة", "en": "Currency Rejected", "pt": "Moeda Rejeitada", "tr": "Para Birimi Reddedildi", "id": "Mata Uang Ditolak"},
    "action_currency_revenue": {"ar": "توزيع إيراد عملة", "en": "Currency Revenue Distributed", "pt": "Receita de Moeda Distribuída", "tr": "Para Birimi Geliri Dağıtıldı", "id": "Pendapatan Mata Uang Didistribusikan"},
    "action_stock_suspend": {"ar": "إيقاف تداول أصل", "en": "Asset Trading Suspended", "pt": "Negociação de Ativo Suspensa", "tr": "Varlık İşlemi Askıya Alındı", "id": "Perdagangan Aset Ditangguhkan"},
    "action_stock_resume": {"ar": "استئناف تداول أصل", "en": "Asset Trading Resumed", "pt": "Negociação de Ativo Retomada", "tr": "Varlık İşlemi Devam Ettirildi", "id": "Perdagangan Aset Dilanjutkan"},
    "days_word": {"ar": "أيام", "en": "days", "pt": "dias", "tr": "gün", "id": "hari"},
    "invest_amount_label": {"ar": "المبلغ اللي عايز تستثمره", "en": "Amount to invest", "pt": "Valor a investir", "tr": "Yatırılacak tutar", "id": "Jumlah untuk diinvestasikan"},
    "invest_btn": {"ar": "استثمر دلوقتي", "en": "Invest Now", "pt": "Investir Agora", "tr": "Şimdi Yatırım Yap", "id": "Investasi Sekarang"},
    "my_investments": {"ar": "استثماراتي", "en": "My Investments", "pt": "Meus Investimentos", "tr": "Yatırımlarım", "id": "Investasi Saya"},
    "invested_col": {"ar": "المبلغ المستثمر", "en": "Invested", "pt": "Investido", "tr": "Yatırılan", "id": "Diinvestasikan"},
    "expected_payout_col": {"ar": "العائد المتوقع", "en": "Expected Payout", "pt": "Retorno Esperado", "tr": "Beklenen Getiri", "id": "Perkiraan Pembayaran"},
    "matures_col": {"ar": "تاريخ الاستحقاق", "en": "Matures On", "pt": "Data de Vencimento", "tr": "Vade Tarihi", "id": "Jatuh Tempo Pada"},
    "status_col": {"ar": "الحالة", "en": "Status", "pt": "Status", "tr": "Durum", "id": "Status"},
    "status_active": {"ar": "شغال", "en": "Active", "pt": "Ativo", "tr": "Aktif", "id": "Aktif"},
    "status_paid": {"ar": "اتصرف", "en": "Paid Out", "pt": "Pago", "tr": "Ödendi", "id": "Sudah Dibayar"},
    "no_investments_yet": {"ar": "مفيش استثمارات لسه.", "en": "No investments yet.", "pt": "Nenhum investimento ainda.", "tr": "Henüz yatırım yok.", "id": "Belum ada investasi."},
    "flash_investment_created": {"ar": "تم فتح استثمار جديد", "en": "New investment opened", "pt": "Novo investimento criado", "tr": "Yeni yatırım açıldı", "id": "Investasi baru dibuka"},
    "flash_investment_min": {"ar": "أقل مبلغ للاستثمار هو", "en": "Minimum investment amount is", "pt": "O investimento mínimo é", "tr": "Minimum yatırım tutarı", "id": "Jumlah investasi minimum adalah"},

    # debts
    "debts": {"ar": "ديون", "en": "Loans", "pt": "Empréstimos", "tr": "Krediler", "id": "Pinjaman"},
    "debts_title": {"ar": "طلب دين / قرض", "en": "Request a Loan", "pt": "Solicitar um Empréstimo", "tr": "Kredi Talep Et", "id": "Ajukan Pinjaman"},
    "debts_request_lede": {"ar": "ابعت طلب دين وأدمن البنك هيراجعه ويوافق أو يرفض.",
                             "en": "Submit a loan request and a bank admin will review it and approve or reject it.",
                             "pt": "Envie um pedido de empréstimo e um admin do banco vai analisá-lo e aprovar ou rejeitar.", "tr": "Bir kredi talebi gönderin, banka yöneticisi inceleyip onaylayacak veya reddedecektir.", "id": "Ajukan permintaan pinjaman dan admin bank akan meninjau serta menyetujui atau menolaknya."},
    "debts_lede": {"ar": "تقدر كمان تتواصل مباشرة مع حد من ملاك أو إدارة البنك على تليجرام لو حابب.",
                    "en": "You can also contact one of the bank's owners or admins directly on Telegram if you'd like.",
                    "pt": "Você também pode falar diretamente com um dos donos ou admins do banco no Telegram, se preferir.", "tr": "İsterseniz Telegram üzerinden bankanın sahiplerinden veya yöneticilerinden biriyle doğrudan iletişime de geçebilirsiniz.", "id": "Anda juga bisa menghubungi salah satu pemilik atau admin bank secara langsung di Telegram jika Anda mau."},
    "debts_contact_label": {"ar": "تواصل مع", "en": "Contact", "pt": "Fale com", "tr": "İletişim", "id": "Kontak"},
    "debts_no_contact": {"ar": "كلم أي حد من ملاك أو إدارة البنك على تليجرام مباشرة عشان تطلب دين.",
                          "en": "Message any of the bank's owners or admins directly on Telegram to request a loan.",
                          "pt": "Fale diretamente com qualquer dono ou admin do banco no Telegram para pedir um empréstimo.", "tr": "Kredi talep etmek için Telegram üzerinden bankanın sahiplerinden veya yöneticilerinden birine mesaj gönderin.", "id": "Kirim pesan ke salah satu pemilik atau admin bank secara langsung di Telegram untuk mengajukan pinjaman."},
    "loan_amount_label": {"ar": "المبلغ المطلوب", "en": "Amount Requested", "pt": "Valor Solicitado", "tr": "Talep Edilen Tutar", "id": "Jumlah yang Diminta"},
    "loan_reason_label": {"ar": "سبب الدين (اختياري)", "en": "Reason for Loan (optional)", "pt": "Motivo do Empréstimo (opcional)", "tr": "Kredi Nedeni (isteğe bağlı)", "id": "Alasan Pinjaman (opsional)"},
    "loan_reason_placeholder": {"ar": "مثلاً: عايز أستثمر في سهم كذا", "en": "e.g. I want to invest in stock X", "pt": "ex: quero investir na ação X", "tr": "örn. X hissesine yatırım yapmak istiyorum", "id": "mis. Saya ingin berinvestasi di saham X"},
    "submit_loan_btn": {"ar": "إرسال الطلب", "en": "Submit Request", "pt": "Enviar Pedido", "tr": "Talebi Gönder", "id": "Kirim Permintaan"},
    "my_loan_requests": {"ar": "طلبات الدين بتاعتي", "en": "My Loan Requests", "pt": "Meus Pedidos de Empréstimo", "tr": "Kredi Taleplerim", "id": "Permintaan Pinjaman Saya"},
    "loan_reason_col": {"ar": "السبب", "en": "Reason", "pt": "Motivo", "tr": "Neden", "id": "Alasan"},
    "no_loan_requests_yet": {"ar": "مفيش طلبات دين لسه.", "en": "No loan requests yet.", "pt": "Nenhum pedido de empréstimo ainda.", "tr": "Henüz kredi talebi yok.", "id": "Belum ada permintaan pinjaman."},
    "no_loan_requests_at_all": {"ar": "مفيش طلبات دين مقدمة لسه.", "en": "No loan requests submitted yet.", "pt": "Nenhum pedido de empréstimo enviado ainda.", "tr": "Henüz gönderilmiş kredi talebi yok.", "id": "Belum ada permintaan pinjaman yang diajukan."},
    "status_approved": {"ar": "تمت الموافقة", "en": "Approved", "pt": "Aprovado", "tr": "Onaylandı", "id": "Disetujui"},
    "approve_btn": {"ar": "موافقة", "en": "Approve", "pt": "Aprovar", "tr": "Onayla", "id": "Setujui"},
    "flash_loan_submitted": {"ar": "تم إرسال طلب الدين، هيتراجع من الأدمن قريبًا", "en": "Loan request submitted, an admin will review it soon", "pt": "Pedido de empréstimo enviado, um admin vai analisá-lo em breve", "tr": "Kredi talebi gönderildi, bir yönetici yakında inceleyecek", "id": "Permintaan pinjaman terkirim, admin akan segera meninjaunya"},
    "flash_loan_approved": {"ar": "تمت الموافقة على الطلب وإضافة المبلغ للرصيد", "en": "Request approved and amount added to balance", "pt": "Pedido aprovado e valor adicionado ao saldo", "tr": "Talep onaylandı ve tutar bakiyeye eklendi", "id": "Permintaan disetujui dan jumlah ditambahkan ke saldo"},
    "flash_loan_rejected": {"ar": "تم رفض الطلب", "en": "Request rejected", "pt": "Pedido rejeitado", "tr": "Talep reddedildi", "id": "Permintaan ditolak"},
    "admin_loans_title": {"ar": "طلبات الديون", "en": "Loan Requests", "pt": "Pedidos de Empréstimo", "tr": "Kredi Talepleri", "id": "Permintaan Pinjaman"},
    "admin_loans_lede": {"ar": "راجع طلبات الدين ووافق عليها أو ارفضها.", "en": "Review loan requests and approve or reject them.", "pt": "Revise os pedidos de empréstimo e aprove ou rejeite.", "tr": "Kredi taleplerini inceleyin ve onaylayın veya reddedin.", "id": "Tinjau permintaan pinjaman dan setujui atau tolak."},
    "admin_loans_pending_title": {"ar": "طلبات معلّقة (تحتاج قرار)", "en": "Pending requests (need a decision)", "pt": "Pedidos pendentes (precisam de decisão)", "tr": "Bekleyen talepler (karar gerekiyor)", "id": "Permintaan tertunda (perlu keputusan)"},
    "admin_loans_approved_title": {"ar": "لسه هيدفع (معتمد، ماتسددش لسه)", "en": "Still to pay (approved, not repaid yet)", "pt": "Ainda a pagar (aprovado, ainda não pago)", "tr": "Henüz ödenecek (onaylandı, henüz ödenmedi)", "id": "Belum dibayar (disetujui, belum lunas)"},
    "admin_loans_history_title": {"ar": "سجل الديون (اختر تصنيف)", "en": "Loan History (choose a category)", "pt": "Histórico de Empréstimos (escolha uma categoria)", "tr": "Kredi Geçmişi (bir kategori seçin)", "id": "Riwayat Pinjaman (pilih kategori)"},
    "admin_loans_repaid_title": {"ar": "اتسدد (دافع)", "en": "Repaid (paid)", "pt": "Pago (quitado)", "tr": "Geri ödendi (ödendi)", "id": "Sudah lunas (dibayar)"},
    "admin_loans_rejected_title": {"ar": "مرفوض", "en": "Rejected", "pt": "Rejeitado", "tr": "Reddedildi", "id": "Ditolak"},
    "no_pending_loans": {"ar": "مفيش طلبات معلّقة دلوقتي.", "en": "No pending requests right now.", "pt": "Nenhum pedido pendente no momento.", "tr": "Şu anda bekleyen talep yok.", "id": "Tidak ada permintaan tertunda saat ini."},
    "no_approved_loans": {"ar": "مفيش ديون لسه هتتدفع دلوقتي.", "en": "No loans still awaiting repayment right now.", "pt": "Nenhum empréstimo aguardando pagamento no momento.", "tr": "Şu anda ödeme bekleyen kredi yok.", "id": "Tidak ada pinjaman yang menunggu pelunasan saat ini."},
    "no_repaid_loans": {"ar": "مفيش ديون اتسددت لسه.", "en": "No loans repaid yet.", "pt": "Nenhum empréstimo pago ainda.", "tr": "Henüz geri ödenmiş kredi yok.", "id": "Belum ada pinjaman yang dilunasi."},
    "no_rejected_loans": {"ar": "مفيش طلبات مرفوضة.", "en": "No rejected requests.", "pt": "Nenhum pedido rejeitado.", "tr": "Reddedilmiş talep yok.", "id": "Tidak ada permintaan yang ditolak."},

    # nav admin-section management labels (تفرقة عن نفس الاسم في الصفحات العادية)
    "nav_manage_investments": {"ar": "إدارة الاستثمارات", "en": "Manage Investments", "pt": "Gerenciar Investimentos", "tr": "Yatırımları Yönet", "id": "Kelola Investasi"},
    "nav_manage_withdrawals": {"ar": "إدارة السحب", "en": "Manage Withdrawals", "pt": "Gerenciar Saques", "tr": "Para Çekmeleri Yönet", "id": "Kelola Penarikan"},
    "nav_manage_loans": {"ar": "إدارة الديون", "en": "Manage Loans", "pt": "Gerenciar Empréstimos", "tr": "Kredileri Yönet", "id": "Kelola Pinjaman"},

    # loan terms & repayment
    "loan_terms_title": {"ar": "مدد السداد ونسبة الفايدة", "en": "Repayment Terms & Interest", "pt": "Prazos e Juros", "tr": "Geri Ödeme Koşulları ve Faiz", "id": "Syarat Pembayaran & Bunga"},
    "loan_default_warning": {"ar": "لو ماسددتش الدين خلال المدة، هيتم نشر اسمك كمحتال، وطردك من الجروبات، ومعادش هيتم التعامل معاك تاني نهائي.",
                               "en": "If you don't repay the loan within the term, you'll be publicly called out as a scammer, removed from the groups, and never dealt with again.",
                               "pt": "Se você não pagar o empréstimo dentro do prazo, seu nome será divulgado publicamente como golpista, você será removido dos grupos e nunca mais será atendido.",
                               "tr": "Krediyi süresi içinde ödemezseniz, adınız dolandırıcı olarak ilan edilir, gruplardan çıkarılırsınız ve bir daha asla sizinle iş yapılmaz.",
                               "id": "Jika Anda tidak melunasi pinjaman dalam jangka waktu tersebut, nama Anda akan diumumkan sebagai penipu, dikeluarkan dari grup, dan tidak akan pernah dilayani lagi."},
    "loan_term_label": {"ar": "مدة السداد", "en": "Repayment Term", "pt": "Prazo de Pagamento", "tr": "Geri Ödeme Süresi", "id": "Jangka Waktu Pembayaran"},
    "loan_term_option": {"ar": "أيام", "en": "days", "pt": "dias", "tr": "gün", "id": "hari"},
    "term_col": {"ar": "المدة", "en": "Term", "pt": "Prazo", "tr": "Süre", "id": "Jangka Waktu"},
    "interest_col": {"ar": "الفايدة", "en": "Interest", "pt": "Juros", "tr": "Faiz", "id": "Bunga"},
    "repay_amount_col": {"ar": "المبلغ المطلوب سداده", "en": "Amount Due", "pt": "Valor Devido", "tr": "Ödenecek Tutar", "id": "Jumlah Terutang"},
    "due_date_col": {"ar": "تاريخ الاستحقاق", "en": "Due Date", "pt": "Data de Vencimento", "tr": "Vade Tarihi", "id": "Tanggal Jatuh Tempo"},
    "repay_now_btn": {"ar": "سدد الدين", "en": "Repay Loan", "pt": "Pagar Empréstimo", "tr": "Krediyi Öde", "id": "Bayar Pinjaman"},
    "status_repaid": {"ar": "تم السداد", "en": "Repaid", "pt": "Pago", "tr": "Ödendi", "id": "Sudah Dibayar"},
    "flash_loan_repaid": {"ar": "تم سداد الدين بنجاح", "en": "Loan repaid successfully", "pt": "Empréstimo pago com sucesso", "tr": "Kredi başarıyla ödendi", "id": "Pinjaman berhasil dibayar"},
    "flash_loan_repay_insufficient": {"ar": "رصيدك مش كفاية لسداد الدين", "en": "Your balance isn't enough to repay this loan", "pt": "Seu saldo não é suficiente para pagar este empréstimo", "tr": "Bu krediyi ödemek için bakiyeniz yeterli değil", "id": "Saldo Anda tidak cukup untuk membayar pinjaman ini"},
    "bot_loan_due_reminder_msg": {"ar": "⏰ تنبيه: باقي يوم واحد بس على ميعاد سداد دينك ({due_date}). المبلغ المطلوب: {amount}. لو معدّيتش الميعاد، هيتسحب المبلغ تلقائي من رصيدك لو موجود، ولو رصيدك مش كفاية هيتم تجميد حسابك لحد ما تسدد. ادخل الموقع وسدد دلوقتي من صفحة \"الديون\" لو عايز تتجنب ده.",
                                     "en": "⏰ Reminder: you have 1 day left until your loan repayment is due ({due_date}). Amount due: {amount}. If you miss the deadline, the amount will be auto-deducted from your balance if available; if your balance isn't enough, your account will be frozen until you repay. Go to the \"Loans\" page on the site to repay now and avoid this.",
                                     "pt": "⏰ Lembrete: falta 1 dia para o vencimento do seu empréstimo ({due_date}). Valor devido: {amount}. Se você perder o prazo, o valor será deduzido automaticamente do seu saldo, se disponível; se seu saldo não for suficiente, sua conta será congelada até o pagamento. Acesse a página \"Empréstimos\" no site para pagar agora e evitar isso.",
                                     "tr": "⏰ Hatırlatma: kredi ödemenize son 1 gün kaldı ({due_date}). Ödenecek tutar: {amount}. Süreyi kaçırırsanız, tutar mevcutsa bakiyenizden otomatik olarak düşülecek; bakiyeniz yetersizse, ödeme yapana kadar hesabınız dondurulacaktır. Bunu önlemek için sitedeki \"Krediler\" sayfasından şimdi ödeyin.",
                                     "id": "⏰ Pengingat: tersisa 1 hari lagi hingga jatuh tempo pembayaran pinjaman Anda ({due_date}). Jumlah yang harus dibayar: {amount}. Jika Anda melewatkan tenggat waktu, jumlah tersebut akan otomatis dipotong dari saldo Anda jika tersedia; jika saldo Anda tidak cukup, akun Anda akan dibekukan hingga Anda membayar. Kunjungi halaman \"Pinjaman\" di situs untuk membayar sekarang dan menghindari hal ini."},
    "bot_loan_auto_repaid_msg": {"ar": "✅ فات ميعاد سداد دينك ومعديتش تسدده، فسحبنا المبلغ ({amount}) تلقائي من رصيدك وتم سداد الدين بالكامل.",
                                   "en": "✅ Your loan's due date passed without repayment, so we automatically deducted the amount ({amount}) from your balance and the loan is now fully repaid.",
                                   "pt": "✅ O prazo do seu empréstimo passou sem pagamento, então deduzimos automaticamente o valor ({amount}) do seu saldo e o empréstimo agora está totalmente pago.",
                                   "tr": "✅ Kredinizin vade tarihi ödeme yapılmadan geçti, bu yüzden tutarı ({amount}) bakiyenizden otomatik olarak düştük ve kredi artık tamamen ödendi.",
                                   "id": "✅ Tanggal jatuh tempo pinjaman Anda telah lewat tanpa pembayaran, jadi kami secara otomatis memotong jumlah ({amount}) dari saldo Anda dan pinjaman kini telah lunas sepenuhnya."},
    "bot_loan_frozen_msg": {"ar": "🔒 فات ميعاد سداد دينك ({amount}) ورصيدك مش كفاية، فتم تجميد حسابك. مش هتقدر تسحب أو تتداول لحد ما تسدد الدين أو يبقى معاك رصيد كفاية (وقتها هيتسحب المبلغ تلقائي ويتفك التجميد).",
                              "en": "🔒 Your loan's due date ({amount}) passed and your balance wasn't enough, so your account has been frozen. You won't be able to withdraw or trade until you repay the loan, or until your balance is enough (at which point the amount will be auto-deducted and the freeze lifted).",
                              "pt": "🔒 O prazo do seu empréstimo ({amount}) passou e seu saldo não era suficiente, então sua conta foi congelada. Você não poderá sacar ou negociar até pagar o empréstimo, ou até que seu saldo seja suficiente (nesse momento o valor será deduzido automaticamente e o congelamento será removido).",
                              "tr": "🔒 Kredinizin vade tarihi ({amount}) geçti ve bakiyeniz yetersizdi, bu yüzden hesabınız donduruldu. Krediyi ödeyene veya bakiyeniz yeterli olana kadar para çekme veya işlem yapamayacaksınız (bu noktada tutar otomatik olarak düşülecek ve dondurma kaldırılacaktır).",
                              "id": "🔒 Tanggal jatuh tempo pinjaman Anda ({amount}) telah lewat dan saldo Anda tidak cukup, sehingga akun Anda telah dibekukan. Anda tidak akan dapat menarik atau berdagang hingga Anda melunasi pinjaman, atau hingga saldo Anda cukup (saat itu jumlah akan otomatis dipotong dan pembekuan akan dicabut)."},
    "account_frozen_banner_title": {"ar": "🔒 حسابك مجمّد", "en": "🔒 Your account is frozen", "pt": "🔒 Sua conta está congelada", "tr": "🔒 Hesabınız donduruldu", "id": "🔒 Akun Anda dibekukan"},
    "account_frozen_banner_body": {"ar": "فات ميعاد سداد دين عليك ورصيدك مش كفاية للسداد التلقائي. مش هتقدر تسحب أو تتداول لحد ما تسدد الدين أو يبقى معاك رصيد كفاية.",
                                     "en": "One of your loans is overdue and your balance isn't enough for automatic repayment. You won't be able to withdraw or trade until you repay the loan or your balance is enough.",
                                     "pt": "Um dos seus empréstimos está vencido e seu saldo não é suficiente para o pagamento automático. Você não poderá sacar ou negociar até pagar o empréstimo ou ter saldo suficiente.",
                                     "tr": "Kredilerinizden biri gecikmiş ve bakiyeniz otomatik ödeme için yeterli değil. Krediyi ödeyene veya bakiyeniz yeterli olana kadar para çekme veya işlem yapamayacaksınız.",
                                     "id": "Salah satu pinjaman Anda telah jatuh tempo dan saldo Anda tidak cukup untuk pembayaran otomatis. Anda tidak akan dapat menarik atau berdagang hingga Anda melunasi pinjaman atau saldo Anda cukup."},
    "loan_due_soon_banner_body": {"ar": "⏰ باقي يوم واحد بس على ميعاد سداد دينك ({amount}) في {due_date}. لو معدّيتش الميعاد، هيتسحب المبلغ تلقائي لو معاك رصيد كفاية، وإلا هيتم تجميد حسابك.",
                                    "en": "⏰ You have 1 day left until your loan of {amount} is due on {due_date}. If you miss it, the amount will be auto-deducted if your balance allows, otherwise your account will be frozen.",
                                    "pt": "⏰ Falta 1 dia para o vencimento do seu empréstimo de {amount} em {due_date}. Se você perder o prazo, o valor será deduzido automaticamente se o seu saldo permitir, caso contrário sua conta será congelada.",
                                    "tr": "⏰ {amount} tutarındaki kredinizin vade tarihi olan {due_date} için son 1 gününüz kaldı. Kaçırırsanız, bakiyeniz izin veriyorsa tutar otomatik düşülecek, aksi halde hesabınız dondurulacaktır.",
                                    "id": "⏰ Tersisa 1 hari lagi hingga pinjaman Anda sebesar {amount} jatuh tempo pada {due_date}. Jika Anda melewatkannya, jumlah tersebut akan otomatis dipotong jika saldo Anda mencukupi, jika tidak akun Anda akan dibekukan."},
    "loan_due_soon_title": {"ar": "⏰ باقي يوم على سداد دينك", "en": "⏰ Your loan is due in 1 day", "pt": "⏰ Seu empréstimo vence em 1 dia", "tr": "⏰ Krediniz 1 gün içinde vadesi doluyor", "id": "⏰ Pinjaman Anda jatuh tempo dalam 1 hari"},
    "action_frozen": {"ar": "🔒 حسابك مجمّد بسبب دين متأخر - سدد أو زوّد رصيدك عشان يتفك التجميد تلقائي.",
                        "en": "🔒 Your account is frozen due to an overdue loan — repay it or top up your balance to have the freeze lifted automatically.",
                        "pt": "🔒 Sua conta está congelada devido a um empréstimo vencido — pague-o ou recarregue seu saldo para que o congelamento seja removido automaticamente.",
                        "tr": "🔒 Hesabınız gecikmiş bir kredi nedeniyle donduruldu — dondurmanın otomatik olarak kaldırılması için ödeyin veya bakiyenizi artırın.",
                        "id": "🔒 Akun Anda dibekukan karena pinjaman yang jatuh tempo — bayar atau tambah saldo Anda agar pembekuan otomatis dicabut."},
    "flash_account_frozen": {"ar": "🔒 حسابك مجمّد بسبب دين متأخر السداد - سدد الدين أو زوّد رصيدك عشان يتفك التجميد تلقائي.",
                               "en": "🔒 Your account is frozen due to an overdue loan — repay it or top up your balance to have the freeze lifted automatically.",
                               "pt": "🔒 Sua conta está congelada devido a um empréstimo vencido — pague-o ou recarregue seu saldo para que o congelamento seja removido automaticamente.",
                               "tr": "🔒 Hesabınız gecikmiş bir kredi nedeniyle donduruldu — dondurmanın otomatik olarak kaldırılması için ödeyin veya bakiyenizi artırın.",
                               "id": "🔒 Akun Anda dibekukan karena pinjaman yang jatuh tempo — bayar atau tambah saldo Anda agar pembekuan otomatis dicabut."},
    "fee_source_loan_repayment": {"ar": "سداد دين", "en": "Loan Repayment", "pt": "Pagamento de Empréstimo", "tr": "Kredi Geri Ödemesi", "id": "Pembayaran Pinjaman"},
    "fee_source_loan_repayment_auto": {"ar": "سداد دين تلقائي (فات الميعاد)", "en": "Auto Loan Repayment (overdue)", "pt": "Pagamento Automático de Empréstimo (vencido)", "tr": "Otomatik Kredi Geri Ödemesi (vadesi geçmiş)", "id": "Pembayaran Pinjaman Otomatis (jatuh tempo)"},


    # treasury
    "treasury_nav": {"ar": "خزينة GNID", "en": "GNID Treasury", "pt": "Tesouro GNID", "tr": "GNID Hazinesi", "id": "Kas GNID"},
    "treasury_title": {"ar": "خزينة GNID", "en": "GNID Treasury", "pt": "Tesouro GNID", "tr": "GNID Hazinesi", "id": "Kas GNID"},
    "treasury_lede": {"ar": "كل عمولات التداول بتتحصل هنا تلقائيًا.",
                        "en": "All trading fees are collected here automatically.",
                        "pt": "Todas as taxas de negociação são coletadas aqui automaticamente.", "tr": "Tüm işlem ücretleri burada otomatik olarak toplanır.", "id": "Semua biaya perdagangan dikumpulkan di sini secara otomatis."},
    "treasury_balance_label": {"ar": "رصيد الخزينة الحالي", "en": "Current Treasury Balance", "pt": "Saldo Atual do Tesouro", "tr": "Mevcut Hazine Bakiyesi", "id": "Saldo Kas Saat Ini"},
    "treasury_total_entries": {"ar": "عدد العمليات المحصّلة", "en": "Fee Entries Collected", "pt": "Entradas de Taxas Coletadas", "tr": "Toplanan Ücret Kayıtları", "id": "Entri Biaya Terkumpul"},
    "bank_liabilities_title": {"ar": "التزامات البنك", "en": "Bank Liabilities", "pt": "Obrigações do Banco", "tr": "Banka Yükümlülükleri", "id": "Kewajiban Bank"},
    "bank_liabilities_lede": {"ar": "إجمالي الفلوس اللي البنك مدين بيها للمستخدمين حاليًا - من استثمارات لسه شغالة وديون لسه ماتسددتش.",
                                "en": "Total money the bank currently owes to users — from active investments and unpaid loans.",
                                "pt": "Total de dinheiro que o banco deve atualmente aos usuários — de investimentos ativos e empréstimos não pagos.",
                                "tr": "Bankanın şu anda kullanıcılara borçlu olduğu toplam para — aktif yatırımlardan ve ödenmemiş kredilerden.",
                                "id": "Total uang yang saat ini terhutang bank kepada pengguna — dari investasi aktif dan pinjaman yang belum dibayar."},
    "total_invested_active_label": {"ar": "إجمالي المبالغ المستثمرة (شغالة حاليًا)", "en": "Total Invested (currently active)", "pt": "Total Investido (ativo no momento)", "tr": "Toplam Yatırılan (şu anda aktif)", "id": "Total Diinvestasikan (saat ini aktif)"},
    "total_investment_payout_due_label": {"ar": "إجمالي المطلوب دفعه للمستثمرين (أصل + عائد)", "en": "Total Owed to Investors (principal + return)", "pt": "Total Devido aos Investidores (principal + retorno)", "tr": "Yatırımcılara Borçlu Olunan Toplam (anapara + getiri)", "id": "Total Terutang ke Investor (pokok + imbal hasil)"},
    "total_loans_owed_label": {"ar": "إجمالي الديون المستحقة للمستخدمين", "en": "Total Outstanding Loans Owed", "pt": "Total de Empréstimos Pendentes", "tr": "Toplam Ödenmemiş Kredi Borcu", "id": "Total Pinjaman Terutang"},
    "total_liabilities_label": {"ar": "إجمالي الالتزامات (استثمارات + ديون)", "en": "Total Liabilities (investments + loans)", "pt": "Total de Obrigações (investimentos + empréstimos)", "tr": "Toplam Yükümlülükler (yatırımlar + krediler)", "id": "Total Kewajiban (investasi + pinjaman)"},
    "treasury_log_title": {"ar": "سجل الخزينة", "en": "Treasury Log", "pt": "Registro do Tesouro", "tr": "Hazine Günlüğü", "id": "Log Kas"},
    "treasury_stocks_value_label": {"ar": "قيمة الأسهم اللي معاها", "en": "Stock Portfolio Value", "pt": "Valor da Carteira de Ações", "tr": "Hisse Portföyü Değeri", "id": "Nilai Portofolio Saham"},
    "treasury_stocks_title": {"ar": "تحويل أسهم للخزينة", "en": "Transfer Shares to Treasury", "pt": "Transferir Ações para o Tesouro", "tr": "Hisseleri Hazineye Transfer Et", "id": "Transfer Saham ke Kas"},
    "treasury_stocks_lede": {"ar": "حوّل أسهم من المتاح للسوق لملكية الخزينة، أو رجّعها للسوق تاني.",
                               "en": "Move shares between the market's available pool and the treasury's ownership, or move them back.",
                               "pt": "Mova ações entre o pool disponível no mercado e a propriedade do tesouro, ou devolva-as.", "tr": "Hisseleri piyasanın mevcut havuzu ile hazinenin sahipliği arasında taşıyın veya geri taşıyın.", "id": "Pindahkan saham antara pool yang tersedia di pasar dan kepemilikan kas, atau kembalikan."},
    "stock_label": {"ar": "السهم", "en": "Stock", "pt": "Ação", "tr": "Hisse", "id": "Saham"},
    "treasury_holds_label": {"ar": "الخزينة معاها", "en": "Treasury holds", "pt": "Tesouro possui", "tr": "Hazine sahip", "id": "Kas memegang"},
    "transfer_direction_label": {"ar": "الاتجاه", "en": "Direction", "pt": "Direção", "tr": "Yön", "id": "Arah"},
    "to_treasury_option": {"ar": "من السوق ← للخزينة", "en": "Market → Treasury", "pt": "Mercado → Tesouro", "tr": "Piyasa → Hazine", "id": "Pasar → Kas"},
    "from_treasury_option": {"ar": "من الخزينة ← للسوق", "en": "Treasury → Market", "pt": "Tesouro → Mercado", "tr": "Hazine → Piyasa", "id": "Kas → Pasar"},
    "transfer_shares_btn": {"ar": "نفّذ التحويل", "en": "Transfer", "pt": "Transferir", "tr": "Transfer Et", "id": "Transfer"},
    "treasury_holdings_title": {"ar": "الأسهم اللي الخزينة مالكاها", "en": "Treasury's Stock Holdings", "pt": "Ações do Tesouro", "tr": "Hazinenin Hisse Varlıkları", "id": "Kepemilikan Saham Kas"},
    "no_treasury_holdings": {"ar": "الخزينة مش مالكة أي أسهم دلوقتي.", "en": "The treasury doesn't hold any shares right now.", "pt": "O tesouro não possui nenhuma ação no momento.", "tr": "Hazine şu anda hiç hisseye sahip değil.", "id": "Kas saat ini tidak memiliki saham apa pun."},
    "flash_shares_transferred": {"ar": "تم تحويل الأسهم", "en": "Shares transferred", "pt": "Ações transferidas", "tr": "Hisseler transfer edildi", "id": "Saham ditransfer"},
    "flash_not_enough_shares": {"ar": "الكمية المطلوبة مش متاحة", "en": "Not enough shares available for that", "pt": "Não há ações suficientes disponíveis", "tr": "Bunun için yeterli hisse yok", "id": "Saham tidak cukup untuk itu"},
    "source_col": {"ar": "المصدر", "en": "Source", "pt": "Origem", "tr": "Kaynak", "id": "Sumber"},
    "no_treasury_entries": {"ar": "مفيش دخل للخزينة لسه.", "en": "No treasury income yet.", "pt": "Nenhuma receita do tesouro ainda.", "tr": "Henüz hazine geliri yok.", "id": "Belum ada pendapatan kas."},
    "fee_source_trade": {"ar": "عمولة صفقة", "en": "Trade Fee", "pt": "Taxa de Negociação", "tr": "İşlem Ücreti", "id": "Biaya Transaksi"},
    "fee_source_admin_payout": {"ar": "تحويل من الخزينة", "en": "Treasury Payout", "pt": "Pagamento do Tesouro", "tr": "Hazine Ödemesi", "id": "Pembayaran Kas"},
    "action_treasury_payout": {"ar": "تحويل فلوس من الخزينة", "en": "Treasury Funds Transferred", "pt": "Fundos do Tesouro Transferidos", "tr": "Hazine Fonları Transfer Edildi", "id": "Dana Kas Ditransfer"},
    "treasury_funds_transfer_title": {"ar": "تحويل فلوس من الخزينة لحساب", "en": "Transfer Treasury Funds to an Account", "pt": "Transferir Fundos do Tesouro para uma Conta", "tr": "Hazine Fonlarını Bir Hesaba Transfer Et", "id": "Transfer Dana Kas ke Akun"},
    "treasury_funds_transfer_lede": {"ar": "ابعت جزء من رصيد الخزينة (فلوس العمولات المجمّعة) لأي حساب بنكي عن طريق آيديه.",
                                       "en": "Send part of the treasury's balance (collected fee income) to any bank account using its ID.",
                                       "pt": "Envie parte do saldo do tesouro (renda de taxas coletadas) para qualquer conta bancária usando seu ID.",
                                       "tr": "Hazine bakiyesinin bir kısmını (toplanan ücret geliri) ID'sini kullanarak herhangi bir banka hesabına gönderin.",
                                       "id": "Kirim sebagian saldo kas (pendapatan biaya yang terkumpul) ke akun bank mana pun menggunakan ID-nya."},
    "flash_insufficient_treasury": {"ar": "رصيد الخزينة مش كفاية للتحويل ده", "en": "The treasury's balance isn't enough for this transfer", "pt": "O saldo do tesouro não é suficiente para esta transferência", "tr": "Hazine bakiyesi bu transfer için yeterli değil", "id": "Saldo kas tidak cukup untuk transfer ini"},
    "flash_treasury_transferred": {"ar": "تم التحويل من الخزينة للحساب بنجاح", "en": "Transferred from the treasury to the account successfully", "pt": "Transferido do tesouro para a conta com sucesso", "tr": "Hazineden hesaba başarıyla transfer edildi", "id": "Berhasil ditransfer dari kas ke akun"},

    # ownership breakdown
    "ownership_breakdown_title": {"ar": "توزيع الملكية", "en": "Ownership Breakdown", "pt": "Distribuição de Propriedade", "tr": "Sahiplik Dağılımı", "id": "Rincian Kepemilikan"},
    "owner_share_label": {"ar": "حصة المالك", "en": "Owner Share", "pt": "Participação do Proprietário", "tr": "Sahip Payı", "id": "Bagian Pemilik"},
    "gnid_share_label": {"ar": "حصة GNID", "en": "GNID Share", "pt": "Participação da GNID", "tr": "GNID Payı", "id": "Bagian GNID"},
    "market_share_label": {"ar": "متاحة للسوق (مطروحة + مملوكة)", "en": "Market Share (offered + owned)", "pt": "Participação de Mercado (ofertada + possuída)", "tr": "Piyasa Payı (sunulan + sahip olunan)", "id": "Bagian Pasar (ditawarkan + dimiliki)"},
    "owner_pct_field": {"ar": "نسبة المالك %", "en": "Owner %", "pt": "% do Proprietário", "tr": "Sahip %", "id": "% Pemilik"},
    "gnid_pct_field": {"ar": "نسبة GNID %", "en": "GNID %", "pt": "% da GNID", "tr": "GNID %", "id": "% GNID"},
    "owner_shares_field": {"ar": "عدد أسهم المالك", "en": "Owner Shares", "pt": "Ações do Proprietário", "tr": "Sahip Hisseleri", "id": "Saham Pemilik"},
    "gnid_shares_field": {"ar": "عدد أسهم GNID", "en": "GNID Shares", "pt": "Ações da GNID", "tr": "GNID Hisseleri", "id": "Saham GNID"},
    "dividend_pct_field": {"ar": "نسبة أرباح المساهمين (%)", "en": "Shareholder Dividend (%)", "pt": "Dividendo dos Acionistas (%)", "tr": "Hissedar Temettüsü (%)", "id": "Dividen Pemegang Saham (%)"},
    "dividend_pct_hint": {"ar": "0 = معطّل", "en": "0 = disabled", "pt": "0 = desativado", "tr": "0 = devre dışı", "id": "0 = nonaktif"},
    "trading_fee_note": {"ar": "عمولة GNID على كل صفقة بيع/شراء", "en": "GNID fee charged on every buy/sell trade", "pt": "Taxa da GNID cobrada em cada negociação", "tr": "Her alış/satış işleminde alınan GNID ücreti", "id": "Biaya GNID dikenakan pada setiap transaksi beli/jual"},

    # admin: manually add investment
    "admin_add_investment_title": {"ar": "إضافة استثمار يدويًا", "en": "Add Investment Manually", "pt": "Adicionar Investimento Manualmente", "tr": "Manuel Yatırım Ekle", "id": "Tambah Investasi Manual"},
    "admin_add_investment_lede": {"ar": "لتسجيل استثمار عملاه بالفعل من قبل (مثلاً بدأ في التليجرام) عشان يتحسب ويترصد تلقائيًا هنا. الرصيد مش بيتخصم من صاحب الاستثمار في الحالة دي.",
                                    "en": "Use this to record an investment that already happened before (e.g. started on Telegram) so it's tracked and auto-paid here. The user's balance is not deducted in this case.",
                                    "pt": "Use isso para registrar um investimento que já aconteceu antes (ex: começou no Telegram) para ser rastreado e pago automaticamente aqui. O saldo do usuário não é debitado nesse caso.", "tr": "Bunu, daha önce gerçekleşmiş bir yatırımı (örneğin Telegram'da başlamış) kaydetmek için kullanın, böylece burada takip edilip otomatik ödenir. Kullanıcının bakiyesi bu durumda düşülmez.", "id": "Gunakan ini untuk mencatat investasi yang sudah terjadi sebelumnya (misalnya dimulai di Telegram) agar dilacak dan dibayar otomatis di sini. Saldo pengguna tidak dikurangi dalam kasus ini."},
    "target_account_id": {"ar": "آي دي حساب المستثمر", "en": "Investor's account ID", "pt": "ID da conta do investidor", "tr": "Yatırımcının hesap kimliği", "id": "ID akun investor"},
    "days_passed_label": {"ar": "عدد الأيام اللي عدت بالفعل", "en": "Days already passed", "pt": "Dias já passados", "tr": "Geçmiş gün sayısı", "id": "Hari yang sudah berlalu"},
    "add_investment_btn": {"ar": "إضافة الاستثمار", "en": "Add Investment", "pt": "Adicionar Investimento", "tr": "Yatırım Ekle", "id": "Tambah Investasi"},
    "all_investments_title": {"ar": "كل الاستثمارات", "en": "All Investments", "pt": "Todos os Investimentos", "tr": "Tüm Yatırımlar", "id": "Semua Investasi"},
    "no_investments_at_all": {"ar": "مفيش استثمارات مسجلة لسه.", "en": "No investments recorded yet.", "pt": "Nenhum investimento registrado ainda.", "tr": "Henüz kaydedilmiş yatırım yok.", "id": "Belum ada investasi yang tercatat."},
    "no_loans_at_all": {"ar": "مفيش طلبات ديون مسجلة لسه.", "en": "No loan requests recorded yet.", "pt": "Nenhum pedido de empréstimo registrado ainda.", "tr": "Henüz kaydedilmiş kredi talebi yok.", "id": "Belum ada permintaan pinjaman yang tercatat."},
    "flash_investment_added_admin": {"ar": "تم إضافة الاستثمار", "en": "Investment added", "pt": "Investimento adicionado", "tr": "Yatırım eklendi", "id": "Investasi ditambahkan"},
    "delete_investment_btn": {"ar": "حذف الاستثمار", "en": "Delete Investment", "pt": "Excluir Investimento", "tr": "Yatırımı Sil", "id": "Hapus Investasi"},
    "confirm_delete_investment": {"ar": "متأكد إنك عايز تحذف الاستثمار ده؟ لو لسه شغال، المبلغ المستثمر هيترجع لرصيد صاحبه.",
                                    "en": "Are you sure you want to delete this investment? If it's still active, the invested amount will be refunded to the user's balance.",
                                    "pt": "Tem certeza que deseja excluir este investimento? Se ainda estiver ativo, o valor investido será devolvido ao saldo do usuário.", "tr": "Bu yatırımı silmek istediğinizden emin misiniz? Hâlâ aktifse, yatırılan tutar kullanıcının bakiyesine iade edilecek.", "id": "Apakah Anda yakin ingin menghapus investasi ini? Jika masih aktif, jumlah yang diinvestasikan akan dikembalikan ke saldo pengguna."},
    "flash_investment_deleted": {"ar": "تم حذف الاستثمار", "en": "Investment deleted", "pt": "Investimento excluído", "tr": "Yatırım silindi", "id": "Investasi dihapus"},
    "flash_investment_updated": {"ar": "تم تحديث الاستثمار", "en": "Investment updated", "pt": "Investimento atualizado", "tr": "Yatırım güncellendi", "id": "Investasi diperbarui"},
    "mods_view_only_note": {"ar": "(عرض بس — التعديل للأدمن فقط)", "en": "(view only — editing is admin-only)", "pt": "(somente visualização — edição é só para admin)", "tr": "(yalnızca görüntüleme — düzenleme sadece yöneticiye özel)", "id": "(hanya lihat — mengedit hanya untuk admin)"},
    "mods_can_edit_note": {"ar": "(تقدر تضيف شركة جديدة وتعدّل أي شركة أنشأها مشرف. الشركات اللي عملها الأدمن مقفولة عليك.)",
                             "en": "(you can add a new company and edit any company created by a mod. Companies created by an admin are locked to you.)",
                             "pt": "(você pode adicionar uma nova empresa e editar qualquer empresa criada por um mod. Empresas criadas por um admin ficam bloqueadas para você.)", "tr": "(yeni bir şirket ekleyebilir ve bir moderatör tarafından oluşturulan herhangi bir şirketi düzenleyebilirsiniz. Bir yönetici tarafından oluşturulan şirketler size kapalıdır.)", "id": "(Anda dapat menambahkan perusahaan baru dan mengedit perusahaan yang dibuat oleh mod. Perusahaan yang dibuat oleh admin terkunci untuk Anda.)"},
    "created_by_admin_locked": {"ar": "الشركة دي عملها الأدمن — المشرف مايقدرش يعدّلها",
                                  "en": "This company was created by an admin — mods can't edit it",
                                  "pt": "Esta empresa foi criada por um admin — mods não podem editá-la", "tr": "Bu şirket bir yönetici tarafından oluşturuldu — moderatörler düzenleyemez", "id": "Perusahaan ini dibuat oleh admin — mod tidak dapat mengeditnya"},
    "action_stock_add": {"ar": "إضافة شركة جديدة", "en": "New Company Added", "pt": "Nova Empresa Adicionada", "tr": "Yeni Şirket Eklendi", "id": "Perusahaan Baru Ditambahkan"},
    "action_stock_delete": {"ar": "حذف شركة", "en": "Company Deleted", "pt": "Empresa Excluída", "tr": "Şirket Silindi", "id": "Perusahaan Dihapus"},
    "action_stock_delete_refund": {"ar": "حذف شركة مع استرجاع الفلوس", "en": "Company Deleted & Refunded", "pt": "Empresa Excluída e Reembolsada", "tr": "Şirket Silindi ve İade Edildi", "id": "Perusahaan Dihapus & Dikembalikan"},
    "action_dividend_distribute": {"ar": "توزيع أرباح مساهمين", "en": "Dividend Distributed", "pt": "Dividendo Distribuído", "tr": "Temettü Dağıtıldı", "id": "Dividen Didistribusikan"},
    "action_notification_send": {"ar": "إرسال إشعار", "en": "Notification Sent", "pt": "Notificação Enviada", "tr": "Bildirim Gönderildi", "id": "Notifikasi Terkirim"},
    "action_investment_delete": {"ar": "حذف استثمار", "en": "Investment Deleted", "pt": "Investimento Excluído", "tr": "Yatırım Silindi", "id": "Investasi Dihapus"},
    "action_investment_edit": {"ar": "تعديل استثمار يدوي", "en": "Manual Investment Edited", "pt": "Investimento Manual Editado", "tr": "Manuel Yatırım Düzenlendi", "id": "Investasi Manual Diedit"},
    "action_withdraw_done": {"ar": "تنفيذ طلب سحب", "en": "Withdrawal Completed", "pt": "Saque Concluído", "tr": "Para Çekme Tamamlandı", "id": "Penarikan Selesai"},
    "action_withdraw_reject": {"ar": "رفض طلب سحب", "en": "Withdrawal Rejected", "pt": "Saque Rejeitado", "tr": "Para Çekme Reddedildi", "id": "Penarikan Ditolak"},
    "vault_ingame_balance_label": {"ar": "رصيد الحساب داخل اللعبة (من التوكين)", "en": "In-Game Vault Balance (from token)", "pt": "Saldo do Cofre no Jogo (do token)", "tr": "Oyun İçi Kasa Bakiyesi (tokendan)", "id": "Saldo Vault Dalam Game (dari token)"},
    "vault_history_title": {"ar": "سجل حركات حساب الخزنة (داخل اللعبة)", "en": "Vault Transaction History (In-Game)", "pt": "Histórico de Transações do Cofre (No Jogo)", "tr": "Kasa İşlem Geçmişi (Oyun İçi)", "id": "Riwayat Transaksi Vault (Dalam Game)"},
    "vault_history_lede": {"ar": "كل التحويلات اللي دخلت وخرجت من حساب الخزنة جوه اللعبة، بلا استثناء - مجلوبة مباشرة من اللعبة.",
                             "en": "Every transfer that came into or out of the vault's in-game account, without exception — fetched directly from the game.",
                             "pt": "Cada transferência que entrou ou saiu da conta do cofre no jogo, sem exceção — obtida diretamente do jogo.",
                             "tr": "Kasanın oyun içi hesabına giren veya çıkan her transfer, istisnasız — doğrudan oyundan alınır.",
                             "id": "Setiap transfer yang masuk atau keluar dari akun vault dalam game, tanpa kecuali — diambil langsung dari game."},
    "vault_history_direction_col": {"ar": "الاتجاه", "en": "Direction", "pt": "Direção", "tr": "Yön", "id": "Arah"},
    "vault_history_counterparty_col": {"ar": "الطرف التاني", "en": "Counterparty", "pt": "Contraparte", "tr": "Karşı Taraf", "id": "Pihak Lain"},
    "vault_history_in": {"ar": "داخل", "en": "In", "pt": "Entrada", "tr": "Gelen", "id": "Masuk"},
    "vault_history_out": {"ar": "خارج", "en": "Out", "pt": "Saída", "tr": "Giden", "id": "Keluar"},
    "vault_history_matched_account_col": {"ar": "الحساب اللي اتحول له", "en": "Credited Account", "pt": "Conta Creditada", "tr": "Hesaba Yatırıldı", "id": "Akun yang Dikreditkan"},
    "vault_history_no_match": {"ar": "⚠️ مفيش حساب اتحول له", "en": "⚠️ No matching account", "pt": "⚠️ Nenhuma conta correspondente", "tr": "⚠️ Eşleşen hesap yok", "id": "⚠️ Tidak ada akun yang cocok"},
    "vault_history_refunded": {"ar": "↩️ اترجعت تلقائيًا للمرسل", "en": "↩️ Auto-refunded to sender", "pt": "↩️ Reembolsado automaticamente", "tr": "↩️ Gönderene otomatik iade edildi", "id": "↩️ Dikembalikan otomatis ke pengirim"},
    "prev_page": {"ar": "السابق", "en": "Previous", "pt": "Anterior", "tr": "Önceki", "id": "Sebelumnya"},
    "next_page": {"ar": "التالي", "en": "Next", "pt": "Próximo", "tr": "Sonraki", "id": "Berikutnya"},
    "action_investment_add_manual": {"ar": "إضافة استثمار يدوي", "en": "Manual Investment Added", "pt": "Investimento Manual Adicionado", "tr": "Manuel Yatırım Eklendi", "id": "Investasi Manual Ditambahkan"},
    "action_loan_approve": {"ar": "موافقة على دين", "en": "Loan Approved", "pt": "Empréstimo Aprovado", "tr": "Kredi Onaylandı", "id": "Pinjaman Disetujui"},
    "action_loan_reject": {"ar": "رفض دين", "en": "Loan Rejected", "pt": "Empréstimo Rejeitado", "tr": "Kredi Reddedildi", "id": "Pinjaman Ditolak"},
    "action_company_approve": {"ar": "قبول تسجيل شركة", "en": "Company Registration Approved", "pt": "Registro de Empresa Aprovado", "tr": "Şirket Kaydı Onaylandı", "id": "Pendaftaran Perusahaan Disetujui"},
    "action_company_reject": {"ar": "رفض تسجيل شركة", "en": "Company Registration Rejected", "pt": "Registro de Empresa Rejeitado", "tr": "Şirket Kaydı Reddedildi", "id": "Pendaftaran Perusahaan Ditolak"},
    "action_stock_edit": {"ar": "تعديل سهم", "en": "Stock Edited", "pt": "Ação Editada", "tr": "Hisse Düzenlendi", "id": "Saham Diedit"},
    "action_order_cancelled_by_admin": {"ar": "إلغاء أمر بيع/شراء", "en": "Buy/Sell Order Cancelled", "pt": "Ordem de Compra/Venda Cancelada", "tr": "Alım/Satım Emri İptal Edildi", "id": "Order Beli/Jual Dibatalkan"},
    "confirm_cancel_order_admin": {"ar": "متأكد إنك عايز تلغي أمر المستخدم ده؟ لو أمر شراء، الفلوس المحجوزة هترجعله تلقائي.",
                                     "en": "Are you sure you want to cancel this user's order? If it's a buy order, their reserved funds will be refunded automatically.",
                                     "pt": "Tem certeza de que deseja cancelar o pedido deste usuário? Se for uma ordem de compra, os fundos reservados serão reembolsados automaticamente.",
                                     "tr": "Bu kullanıcının emrini iptal etmek istediğinizden emin misiniz? Bir alım emriyse, ayrılan fonlar otomatik olarak iade edilecektir.",
                                     "id": "Apakah Anda yakin ingin membatalkan order pengguna ini? Jika ini order beli, dana yang dicadangkan akan dikembalikan secara otomatis."},
    "performed_by_col": {"ar": "الدور", "en": "Role", "pt": "Função", "tr": "Rol", "id": "Peran"},
    "role_admin": {"ar": "أدمن", "en": "Admin", "pt": "Admin", "tr": "Yönetici", "id": "Admin"},
    "role_mod": {"ar": "مشرف", "en": "Mod", "pt": "Mod", "tr": "Moderatör", "id": "Mod"},
    "deposits_and_transfers": {"ar": "توكين", "en": "Token", "pt": "Token", "tr": "Token", "id": "Token"},
    "vault_status_working": {"ar": "شغال ✅ — التوكين متصل والإيداعات بتتحسب تلقائي", "en": "Working ✅ — token connected, deposits are auto-credited", "pt": "Funcionando ✅ — token conectado, depósitos são creditados automaticamente", "tr": "Çalışıyor ✅ — token bağlı, yatırmalar otomatik olarak yatırılıyor", "id": "Berfungsi ✅ — token terhubung, setoran dikreditkan otomatis"},
    "vault_status_broken": {"ar": "متوقف ❌ — التوكين مش شغال، الإيداعات مش بتتحسب تلقائي دلوقتي", "en": "Down ❌ — token isn't working, deposits aren't being auto-credited right now", "pt": "Parado ❌ — o token não está funcionando, depósitos não estão sendo creditados automaticamente", "tr": "Çalışmıyor ❌ — token çalışmıyor, yatırmalar şu anda otomatik yatırılmıyor", "id": "Tidak Berfungsi ❌ — token tidak berfungsi, setoran saat ini tidak dikreditkan otomatis"},
    "vault_status_not_set": {"ar": "متعرفش عليه لسه — حط التوكين تحت وسيب", "en": "Not configured yet — enter the token below", "pt": "Ainda não configurado — insira o token abaixo", "tr": "Henüz yapılandırılmadı — aşağıya tokeni girin", "id": "Belum dikonfigurasi — masukkan token di bawah ini"},

    # withdrawals
    "withdraw": {"ar": "سحب", "en": "Withdraw", "pt": "Saque", "tr": "Para Çek", "id": "Tarik"},
    "withdraw_title": {"ar": "طلب سحب رصيد", "en": "Withdrawal Request", "pt": "Solicitação de Saque", "tr": "Para Çekme Talebi", "id": "Permintaan Penarikan"},
    "withdraw_lede": {"ar": "ابعت رابط حسابك داخل اللعبة والمبلغ اللي عايز تسحبه. الأدمن هيحول لك يدويًا وبعدين يقفل الطلب.",
                       "en": "Send the link to your in-game account and the amount you want to withdraw. An admin will transfer it manually and then close the request.",
                       "pt": "Envie o link da sua conta no jogo e o valor que deseja sacar. Um admin vai transferir manualmente e depois fechar a solicitação.", "tr": "Oyun içi hesabınızın bağlantısını ve çekmek istediğiniz tutarı gönderin. Bir yönetici manuel olarak transfer edip talebi kapatacak.", "id": "Kirim tautan akun dalam game Anda dan jumlah yang ingin ditarik. Admin akan mentransfernya secara manual lalu menutup permintaan."},
    "account_link_label": {"ar": "رابط حسابك داخل اللعبة", "en": "Your in-game account link", "pt": "Link da sua conta no jogo", "tr": "Oyun içi hesap bağlantınız", "id": "Tautan akun dalam game Anda"},
    "account_link_hint": {"ar": "لازم يكون بالشكل ده بالظبط: https://diplomacia.com.tr/profile/player/1348",
                            "en": "Must be in exactly this format: https://diplomacia.com.tr/profile/player/1348",
                            "pt": "Deve estar exatamente neste formato: https://diplomacia.com.tr/profile/player/1348",
                            "tr": "Tam olarak şu formatta olmalı: https://diplomacia.com.tr/profile/player/1348",
                            "id": "Harus dalam format persis ini: https://diplomacia.com.tr/profile/player/1348"},
    "flash_bad_account_link": {"ar": "رابط الحساب غلط. لازم يكون بالشكل ده بالظبط: https://diplomacia.com.tr/profile/player/1348",
                                 "en": "Invalid account link. Must be exactly in this format: https://diplomacia.com.tr/profile/player/1348",
                                 "pt": "Link da conta inválido. Deve estar exatamente neste formato: https://diplomacia.com.tr/profile/player/1348",
                                 "tr": "Geçersiz hesap bağlantısı. Tam olarak şu formatta olmalı: https://diplomacia.com.tr/profile/player/1348",
                                 "id": "Tautan akun tidak valid. Harus dalam format persis ini: https://diplomacia.com.tr/profile/player/1348"},
    "withdraw_account_name_label": {"ar": "اسم الحساب داخل اللعبة (اختياري)", "en": "Account name in-game (optional)", "pt": "Nome da conta no jogo (opcional)", "tr": "Oyun içi hesap adı (isteğe bağlı)", "id": "Nama akun dalam game (opsional)"},
    "withdraw_amount_label": {"ar": "المبلغ المطلوب سحبه", "en": "Amount to withdraw", "pt": "Valor a sacar", "tr": "Çekilecek tutar", "id": "Jumlah untuk ditarik"},
    "request_withdraw_btn": {"ar": "إرسال طلب السحب", "en": "Submit Withdrawal Request", "pt": "Enviar Solicitação de Saque", "tr": "Para Çekme Talebi Gönder", "id": "Kirim Permintaan Penarikan"},
    "my_withdrawals": {"ar": "طلبات السحب بتاعتي", "en": "My Withdrawal Requests", "pt": "Minhas Solicitações de Saque", "tr": "Para Çekme Taleplerim", "id": "Permintaan Penarikan Saya"},
    "link_col": {"ar": "الرابط", "en": "Link", "pt": "Link", "tr": "Bağlantı", "id": "Tautan"},
    "no_withdrawals_yet": {"ar": "مفيش طلبات سحب لسه.", "en": "No withdrawal requests yet.", "pt": "Nenhuma solicitação de saque ainda.", "tr": "Henüz para çekme talebi yok.", "id": "Belum ada permintaan penarikan."},
    "flash_withdraw_created": {"ar": "تم إرسال طلب السحب، هيتنفذ من الأدمن قريبًا", "en": "Withdrawal request submitted, an admin will process it soon", "pt": "Solicitação de saque enviada, um admin vai processá-la em breve", "tr": "Para çekme talebi gönderildi, bir yönetici yakında işleme alacak", "id": "Permintaan penarikan terkirim, admin akan segera memprosesnya"},
    "flash_withdraw_cancelled": {"ar": "تم إلغاء طلب السحب وإرجاع المبلغ لرصيدك", "en": "Withdrawal request cancelled and the amount was returned to your balance", "pt": "Solicitação de saque cancelada e o valor foi devolvido ao seu saldo", "tr": "Para çekme talebi iptal edildi ve tutar bakiyenize iade edildi", "id": "Permintaan penarikan dibatalkan dan jumlahnya dikembalikan ke saldo Anda"},
    "status_cancelled": {"ar": "ملغي", "en": "Cancelled", "pt": "Cancelado", "tr": "İptal Edildi", "id": "Dibatalkan"},
    "cancel_withdraw_btn": {"ar": "إلغاء الطلب", "en": "Cancel Request", "pt": "Cancelar Solicitação", "tr": "Talebi İptal Et", "id": "Batalkan Permintaan"},
    "confirm_cancel_withdraw": {"ar": "متأكد إنك عايز تلغي طلب السحب ده؟ المبلغ هيرجع لرصيدك فورًا.",
                                  "en": "Are you sure you want to cancel this withdrawal request? The amount will be returned to your balance immediately.",
                                  "pt": "Tem certeza de que deseja cancelar esta solicitação de saque? O valor será devolvido ao seu saldo imediatamente.",
                                  "tr": "Bu para çekme talebini iptal etmek istediğinizden emin misiniz? Tutar hemen bakiyenize iade edilecek.",
                                  "id": "Yakin ingin membatalkan permintaan penarikan ini? Jumlahnya akan segera dikembalikan ke saldo Anda."},
    "status_pending": {"ar": "قيد الانتظار", "en": "Pending", "pt": "Pendente", "tr": "Beklemede", "id": "Tertunda"},
    "status_done": {"ar": "تم", "en": "Done", "pt": "Concluído", "tr": "Tamamlandı", "id": "Selesai"},
    "status_rejected": {"ar": "مرفوض", "en": "Rejected", "pt": "Rejeitado", "tr": "Reddedildi", "id": "Ditolak"},
    "admin_withdrawals_title": {"ar": "طلبات السحب", "en": "Withdrawal Requests", "pt": "Solicitações de Saque", "tr": "Para Çekme Talepleri", "id": "Permintaan Penarikan"},
    "admin_withdrawals_lede": {"ar": "حوّل المبلغ للمستخدم يدويًا جوه اللعبة على الرابط اللي بعته، وبعدها اضغط تم.",
                                "en": "Manually transfer the amount to the user in-game using the link they sent, then click Done.",
                                "pt": "Transfira o valor manualmente para o usuário no jogo usando o link enviado, depois clique em Concluído.", "tr": "Tutarı, kullanıcının gönderdiği bağlantıyı kullanarak oyun içinde manuel olarak transfer edin, ardından Tamamlandı'ya tıklayın.", "id": "Transfer jumlah tersebut secara manual kepada pengguna dalam game menggunakan tautan yang mereka kirim, lalu klik Selesai."},
    "mark_done_btn": {"ar": "تم التحويل", "en": "Mark as Done", "pt": "Marcar como Concluído", "tr": "Tamamlandı Olarak İşaretle", "id": "Tandai Selesai"},
    "auto_send_btn": {"ar": "⚡ إرسال تلقائي", "en": "⚡ Auto-Send", "pt": "⚡ Enviar Automaticamente", "tr": "⚡ Otomatik Gönder", "id": "⚡ Kirim Otomatis"},
    "flash_auto_send_no_token": {"ar": "توكن الخزنة مش متظبط، محتاج تنفذ الطلب ده يدوي", "en": "The vault token isn't configured — you'll need to process this manually", "pt": "O token do vault não está configurado — você precisará processar isso manualmente", "tr": "Vault tokeni yapılandırılmamış — bunu manuel olarak işlemeniz gerekecek", "id": "Token vault belum dikonfigurasi — Anda perlu memprosesnya secara manual"},
    "flash_auto_send_bad_link": {"ar": "مقدرتش أطلع رقم اللاعب من الرابط ده، محتاج تنفذ الطلب يدوي", "en": "Couldn't extract the player's ID from that link — you'll need to process this manually", "pt": "Não foi possível extrair o ID do jogador desse link — você precisará processar isso manualmente", "tr": "Bu bağlantıdan oyuncu kimliği çıkarılamadı — bunu manuel olarak işlemeniz gerekecek", "id": "Tidak dapat mengekstrak ID pemain dari tautan itu — Anda perlu memprosesnya secara manual"},
    "flash_auto_send_player_not_found": {"ar": "مقدرتش ألاقي اللاعب ده في اللعبة، محتاج تنفذ الطلب يدوي", "en": "Couldn't find that player in the game — you'll need to process this manually", "pt": "Não foi possível encontrar esse jogador no jogo — você precisará processar isso manualmente", "tr": "Bu oyuncu oyunda bulunamadı — bunu manuel olarak işlemeniz gerekecek", "id": "Tidak dapat menemukan pemain itu di game — Anda perlu memprosesnya secara manual"},
    "flash_auto_send_failed": {"ar": "فشل التحويل التلقائي، محتاج تنفذ الطلب يدوي", "en": "Automatic transfer failed — you'll need to process this manually", "pt": "A transferência automática falhou — você precisará processar isso manualmente", "tr": "Otomatik transfer başarısız oldu — bunu manuel olarak işlemeniz gerekecek", "id": "Transfer otomatis gagal — Anda perlu memprosesnya secara manual"},
    "flash_auto_send_success": {"ar": "تم التحويل التلقائي بنجاح لـ {username} ⚡", "en": "Automatic transfer succeeded for {username} ⚡", "pt": "Transferência automática bem-sucedida para {username} ⚡", "tr": "{username} için otomatik transfer başarılı oldu ⚡", "id": "Transfer otomatis berhasil untuk {username} ⚡"},
    "action_withdraw_auto_sent": {"ar": "تحويل سحب تلقائي", "en": "Auto Withdrawal Sent", "pt": "Saque Automático Enviado", "tr": "Otomatik Para Çekme Gönderildi", "id": "Penarikan Otomatis Terkirim"},
    "reject_btn": {"ar": "رفض", "en": "Reject", "pt": "Rejeitar", "tr": "Reddet", "id": "Tolak"},
    "confirm_reject_withdraw": {"ar": "متأكد إنك عايز ترفض الطلب ده؟ الرصيد هيترجع للمستخدم.",
                                  "en": "Are you sure you want to reject this request? The balance will be refunded to the user.",
                                  "pt": "Tem certeza que deseja rejeitar essa solicitação? O saldo será devolvido ao usuário.", "tr": "Bu talebi reddetmek istediğinizden emin misiniz? Bakiye kullanıcıya iade edilecek.", "id": "Apakah Anda yakin ingin menolak permintaan ini? Saldo akan dikembalikan ke pengguna."},
    "flash_withdraw_done": {"ar": "تم تنفيذ الطلب", "en": "Request marked as done", "pt": "Solicitação marcada como concluída", "tr": "Talep tamamlandı olarak işaretlendi", "id": "Permintaan ditandai selesai"},
    "flash_withdraw_rejected": {"ar": "تم رفض الطلب وإرجاع الرصيد", "en": "Request rejected and balance refunded", "pt": "Solicitação rejeitada e saldo devolvido", "tr": "Talep reddedildi ve bakiye iade edildi", "id": "Permintaan ditolak dan saldo dikembalikan"},
    "no_pending_withdrawals": {"ar": "مفيش طلبات سحب معلقة.", "en": "No pending withdrawal requests.", "pt": "Nenhuma solicitação de saque pendente.", "tr": "Bekleyen para çekme talebi yok.", "id": "Tidak ada permintaan penarikan tertunda."},
})


def tr(key):
    lang = session.get("lang", DEFAULT_LANG)
    entry = TR.get(key, {})
    # لو المفتاح مترجمش للغة دي (حاجة جديدة اتضافت بعد الترجمة)، نرجع بالإنجليزي بدل ما يبان اسم المفتاح الخام
    return entry.get(lang) or entry.get("en") or key


def tr_bg(key, lang="ar"):
    """زي tr() بالظبط، بس من غير الاعتماد على session - عشان نستخدمها في المهام
    اللي بتشتغل في الخلفية (زي إشعارات تليجرام التلقائية) واللي مفيهاش request context أصلاً."""
    entry = TR.get(key, {})
    return entry.get(lang) or entry.get("en") or key


def verified_badge(user):
    """شارة صغيرة ✅ جنب اسم أي مستخدم موثّق - تتظهر في أي جدول بيعرض اسم مستخدم."""
    if user is not None and getattr(user, "telegram_verified", False):
        return ' <span class="verified-badge" title="Verified">✅</span>'
    return ""


def pending_loans_count():
    """عدد طلبات الديون المعلقة - بتتظهر كإشعار أحمر للأدمن/المشرف بس."""
    if not (current_user.is_authenticated and (current_user.is_admin or current_user.is_mod)):
        return 0
    return LoanRequest.query.filter_by(status="pending").count()


def pending_withdrawals_count():
    """عدد طلبات السحب المعلقة - بتتظهر كإشعار أحمر للأدمن/المشرف بس."""
    if not (current_user.is_authenticated and (current_user.is_admin or current_user.is_mod)):
        return 0
    return WithdrawalRequest.query.filter_by(status="pending").count()


def pending_company_requests_count():
    """عدد طلبات تسجيل الشركات المعلقة - بتتظهر كإشعار أحمر للأدمن/المشرف بس."""
    if not (current_user.is_authenticated and (current_user.is_admin or current_user.is_mod)):
        return 0
    return CompanyRequest.query.filter_by(status="pending").count()


def pending_currency_requests_count():
    """عدد طلبات إصدار العملات المعلقة - بتتظهر كإشعار أحمر للأدمن/المشرف بس."""
    if not (current_user.is_authenticated and (current_user.is_admin or current_user.is_mod)):
        return 0
    return CurrencyRequest.query.filter_by(status="pending").count()


def unread_notifications_count():
    """عدد الإشعارات العامة اللي المستخدم لسه ماشافهاش - بتتظهر كرقم فوق زرار الجرس."""
    if not current_user.is_authenticated:
        return 0
    latest = db.session.query(db.func.max(Notification.id)).scalar() or 0
    seen = current_user.last_seen_notification_id or 0
    return max(0, latest - seen)


def get_csrf_token():
    """بيرجع توكن CSRF ثابت لجلسة المستخدم الحالية، وبينشئ واحد جديد لو مفيش."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(24)
        session["csrf_token"] = token
    return token


app.jinja_env.globals["tr"] = tr
app.jinja_env.globals["LANGUAGES"] = LANGUAGES
app.jinja_env.globals["STOCK_ICONS"] = STOCK_ICONS
app.jinja_env.globals["APP_VERSION"] = APP_VERSION
app.jinja_env.globals["LOGO_DATA_URI"] = LOGO_DATA_URI
app.jinja_env.globals["vbadge"] = verified_badge
app.jinja_env.globals["pending_loans_count"] = pending_loans_count
app.jinja_env.globals["pending_withdrawals_count"] = pending_withdrawals_count
app.jinja_env.globals["pending_company_requests_count"] = pending_company_requests_count
app.jinja_env.globals["pending_currency_requests_count"] = pending_currency_requests_count
app.jinja_env.globals["unread_notifications_count"] = unread_notifications_count
app.jinja_env.globals["COMPANY_FEATURE_ENABLED"] = COMPANY_FEATURE_ENABLED
app.jinja_env.globals["csrf_token"] = get_csrf_token
app.jinja_env.filters["money"] = format_money
app.jinja_env.filters["tglink"] = telegram_link


@app.before_request
def ensure_lang():
    if "lang" not in session:
        # أول زيارة: نحاول نتعرف على لغة المتصفح ونختار أقرب لغة مدعومة تلقائيًا
        detected = request.accept_languages.best_match(list(LANGUAGES.keys()))
        session["lang"] = detected or DEFAULT_LANG


# ============================================================
# حماية بسيطة ضد السكرابنج/البوتات: حد أقصى للطلبات لكل IP + منع فهرسة محركات البحث
# ============================================================
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 90  # طلب عادي من متصفح حقيقي ما بيوصلش للرقم ده في دقيقة، سكرابر آلي بيوصله بسرعة
_rate_limit_buckets = {}  # {ip: [timestamps]} - في الميموري بس، كافي لسيرفر واحد
_login_failure_buckets = {}  # {ip: [timestamps]} - محاولات دخول غلط، منفصلة عن الحد العام

# يوزر-إيجنتس شائعة لأدوات السكرابنج والبوتات الآلية - بنرفضهم على طول قبل أي معالجة
BLOCKED_UA_SNIPPETS = (
    "scrapy", "python-requests", "curl/", "wget/", "httpclient", "aiohttp",
    "go-http-client", "libwww-perl", "phantomjs", "headlesschrome",
)


@app.before_request
def block_scrapers_and_rate_limit():
    ua = (request.headers.get("User-Agent") or "").lower()
    if any(snippet in ua for snippet in BLOCKED_UA_SNIPPETS):
        return "forbidden", 403

    # الـ webhook بتاع تليجرام ومهمات الخلفية مش خاضعة للحد ده - مصدرها معروف ومحدود أصلاً
    if request.path.startswith("/telegram/webhook"):
        return

    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    now = datetime.utcnow().timestamp()
    bucket = _rate_limit_buckets.setdefault(ip, [])
    # نشيل أي طلبات أقدم من نافذة الوقت
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.pop(0)
    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        return "too many requests", 429
    bucket.append(now)

    # تنضيف دوري بسيط عشان القاموس ميكبرش على طول لو فيه IPs كتير قديمة
    if len(_rate_limit_buckets) > 5000:
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        for k in list(_rate_limit_buckets.keys()):
            if not _rate_limit_buckets[k] or _rate_limit_buckets[k][-1] < cutoff:
                _rate_limit_buckets.pop(k, None)


@app.after_request
def add_anti_scraping_headers(response):
    # نمنع محركات البحث والأدوات الآلية من فهرسة أو حفظ أي صفحة في الموقع
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@app.before_request
def verify_csrf_token():
    """حماية CSRF بسيطة: أي POST من فورم حقيقي في الموقع بيبعت توكن الجلسة معاه (اتحط تلقائيًا
    عن طريق الـ JS في BASE)، ولو مش متطابق مع اللي متسجل في جلسة المستخدم، بنرفض الطلب.
    الـ webhook بتاع تليجرام مستثنى لأنه مش فورم من متصفح أصلاً وليه حماية تانية (secret token)."""
    if request.method != "POST":
        return
    if request.path.startswith("/telegram/webhook"):
        return
    submitted = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not submitted or not secrets.compare_digest(submitted, expected):
        return "invalid or expired form session, please refresh the page and try again", 403


@app.route("/robots.txt")
def robots_txt():
    return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")


@app.route("/lang/<code>")
def set_lang(code):
    if code in LANGUAGES:
        session["lang"] = code
    return redirect(request.referrer or url_for("login"))


# ============================================================
# Models
# ============================================================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.String(12), unique=True, nullable=False)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    telegram_username = db.Column(db.String(80), nullable=False)
    game_username = db.Column(db.String(120))
    game_uid = db.Column(db.String(120))
    balance = db.Column(db.Float, default=0.0)
    is_admin = db.Column(db.Boolean, default=False)
    is_mod = db.Column(db.Boolean, default=False)  # مشرف: يشوف الاستثمارات/الإيداعات/السحب بس، بدون صلاحيات تعديل
    telegram_chat_id = db.Column(db.String(40))            # آيدي محادثة تليجرام بعد التوثيق
    telegram_verified = db.Column(db.Boolean, default=False)  # اتوثق عن طريق بوت تليجرام ولا لأ
    telegram_verify_code = db.Column(db.String(20))        # كود مؤقت لربط الحساب بالبوت
    telegram_has_username = db.Column(db.Boolean, default=True)  # الحساب الموثّق فعليًا معاه يوزر عام (@) ولا لأ (بعض حسابات تليجرام مفيهاش يوزر عام أصلاً)
    is_frozen = db.Column(db.Boolean, default=False)  # الحساب مجمّد بسبب دين متأخر السداد ومفيهوش فلوس كفاية
    frozen_reason = db.Column(db.String(50))          # سبب التجميد (unpaid_loan حاليًا)
    username_changed = db.Column(db.Boolean, default=False)  # استخدم فرصة تغيير اسم المستخدم (مرة واحدة بس) ولا لأ
    last_seen_notification_id = db.Column(db.Integer, default=0)  # آخر إشعار شافه المستخدم - لحساب عدد الإشعارات غير المقروءة
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Notification(db.Model):
    """إشعار عام يبعته الأدمن لكل المستخدمين (تحديثات، إعلانات، إلخ) - بيظهر في زرار الجرس."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    body = db.Column(db.Text, nullable=False)
    admin_username = db.Column(db.String(80), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def generate_account_id():
    """
    آي دي بنكي تسلسلي يبدأ من 1، ولازم يفضل أصغر من DEPOSIT_UNIT
    عشان يتشفر جوه مبلغ الإيداع (المبلغ = النقاط × DEPOSIT_UNIT + account_id)
    """
    last_id = db.session.query(db.func.max(db.cast(User.account_id, db.Integer))).scalar()
    next_id = (last_id or 0) + 1
    if next_id >= DEPOSIT_UNIT:
        raise ValueError("وصلنا للحد الأقصى لعدد الحسابات المسموح به مع DEPOSIT_UNIT الحالي")
    return str(next_id)


class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)  # أيقونة العملة (مش لازم تبقى فريدة، تقدر تتكرر بين الأسهم)
    name = db.Column(db.String(120), nullable=False)  # اسم الشركة
    admin_price = db.Column(db.Float, nullable=False)  # سعر السهم عند الطرح (IPO) - السعر الفعلي بيتحدد من آخر صفقة
    admin_supply = db.Column(db.Integer, default=0)   # عدد الأسهم المتاحة للبيع حاليًا (من نصيب السوق)
    description = db.Column(db.Text, default="")
    sector = db.Column(db.String(80), default="")
    owner_name = db.Column(db.String(120), default="")
    owner_account_id = db.Column(db.String(20), default="")  # آيدي حساب المالك جوه البنك (لو المالك مستخدم مسجل)
    creator_username = db.Column(db.String(80), default="")  # مين أنشأ السهم ده
    creator_role = db.Column(db.String(10), default="admin")  # admin / mod - عشان نعرف مين مسموحله يعدله
    total_shares = db.Column(db.Integer, default=0)  # لو 0، بيتحسب تلقائي = المتاح + المملوك (شركات قديمة قبل الميزة دي)
    owner_shares = db.Column(db.Integer, default=0)   # حصة مالك الشركة (محجوزة، مش للبيع)
    gnid_shares = db.Column(db.Integer, default=0)    # حصة GNID/البنك (محجوزة، مش للبيع)
    listed_at = db.Column(db.DateTime, default=datetime.utcnow)
    dividend_pct = db.Column(db.Float, default=0)  # نسبة الأرباح اللي بتتوزع أسبوعيًا على أكبر 5 مساهمين (0 = معطّل)
    asset_type = db.Column(db.String(10), default="stock")  # stock (سهم شركة عادي) / currency (عملة مُصدرة من لاعب)
    suspended = db.Column(db.Boolean, default=False)  # إيقاف التداول مؤقتًا للصيانة - بيمنع أي أمر جديد أو تنفيذ

    def shares_outstanding(self):
        """إجمالي عدد الأسهم الفعلي (لو الأدمن مسجلش رقم صريح، بنحسبه من المتاح + المملوك)."""
        if self.total_shares and self.total_shares > 0:
            return self.total_shares
        owned = db.session.query(db.func.coalesce(db.func.sum(Holding.quantity), 0)) \
            .filter(Holding.stock_id == self.id).scalar() or 0
        return self.admin_supply + owned + self.owner_shares + self.gnid_shares

    def ownership_breakdown(self):
        """نسب الملكية التلاتة: المالك / GNID / السوق (المتاح + المملوك من المستخدمين)."""
        total = self.shares_outstanding()
        market_shares = max(total - self.owner_shares - self.gnid_shares, 0)
        if total <= 0:
            return {"owner_pct": 0, "gnid_pct": 0, "market_pct": 0,
                    "owner_shares": self.owner_shares, "gnid_shares": self.gnid_shares, "market_shares": 0}
        return {
            "owner_pct": self.owner_shares / total * 100,
            "gnid_pct": self.gnid_shares / total * 100,
            "market_pct": market_shares / total * 100,
            "owner_shares": self.owner_shares, "gnid_shares": self.gnid_shares, "market_shares": market_shares,
        }

    def price_stats(self):
        """يرجع dict فيه السعر الحالي، الافتتاحي، أعلى، أقل، والتغيير - محسوبة من سجل الصفقات الفعلي.
        التغيير (change/pct) بيتقارن بالسعر زي ما كان من 24 ساعة، مش بآخر صفقة مباشرة - عشان
        يعكس أداء السهم خلال يوم كامل بدل ما يتغير بأي صفقة صغيرة حصلت من ثانية.

        ملحوظة: صفقات الطرح الرسمي (IPO) بتتم دايمًا بسعر ثابت (admin_price) بيحدده الأدمن،
        مش بسعر السوق - فهي مش "اكتشاف سعر" حقيقي زي صفقات السوق بين الأفراد أو تحركات
        الضغط التلقائية. لو ضمّيناها في حساب السعر الحالي، أي حد يشتري IPO كان بيرجّع السعر
        المعروض لنفس السعر الثابت القديم فورًا، حتى لو السوق فعليًا اتحرك لسعر مختلف تمامًا -
        وده اللي كان بيدي شكل السعر إنه "بيرتد" بشكل مصطنع مش طبيعي. عشان كده بنستبعدها هنا."""
        trades = (Trade.query.filter_by(stock_id=self.id).filter(Trade.source != "ipo")
                  .order_by(Trade.created_at.asc()).all())
        prices = [t.price for t in trades]
        if not prices:
            prices = [self.admin_price]
        current = prices[-1]
        opening = prices[0]

        cutoff = datetime.utcnow() - timedelta(hours=24)
        # حماية من صفقات قديمة "غلط" حصلت قبل ما نضيف حماية نطاق السعر (PRICE_BAND_PERCENT) -
        # لو سعرها بعيد جدًا (أكتر من 10 أضعاف أو أقل من عُشر) عن السعر الحالي، بنتجاهلها كمرجع
        # للتغيير خلال 24 ساعة عشان النسبة ما تطلعش رقم خيالي غير منطقي زي +96000%.
        price_24h_ago = self.admin_price
        for t in trades:
            if t.created_at <= cutoff:
                if current > 0 and (t.price < current / 10 or t.price > current * 10):
                    continue  # صفقة شاذة - نتخطاها كمرجع بدون ما نوقف البحث عن نقطة أحسن
                price_24h_ago = t.price
            else:
                break

        change = current - price_24h_ago
        pct = (change / price_24h_ago * 100) if price_24h_ago else 0.0
        return {
            "current": current, "opening": opening, "prev": price_24h_ago,
            "high": max(prices), "low": min(prices),
            "change": change, "pct": pct,
        }

    def market_cap(self):
        return self.price_stats()["current"] * self.shares_outstanding()


class Trade(db.Model):
    """سجل دائم لكل عملية بيع/شراء فعلية حصلت على السهم - الأساس اللي المخططات والإحصائيات مبنية عليه.
    السجلات دي منعملش عليها تعديل أو حذف أبدًا، عشان التاريخ يفضل صحيح 100%."""
    id = db.Column(db.Integer, primary_key=True)
    stock_id = db.Column(db.Integer, db.ForeignKey("stock.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # ممكن يبقى None لو المشتري اتحذف حسابه بعدين
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"))  # None = طرح مباشر من الأدمن (IPO) أو البائع اتحذف حسابه بعدين
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)  # سعر السهم الواحد وقت الصفقة
    fee = db.Column(db.Float, default=0)  # عمولة GNID المحصّلة من الصفقة دي (بتروح للخزينة)
    source = db.Column(db.String(10), default="ipo")  # ipo / market
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    stock = db.relationship("Stock")
    buyer = db.relationship("User", foreign_keys=[buyer_id])
    seller = db.relationship("User", foreign_keys=[seller_id])

    def total_value(self):
        return self.quantity * self.price


class TreasuryEntry(db.Model):
    """سجل دخل خزينة GNID - كل عمولة تداول بتتسجل هنا للأبد، ما بتتمسحش."""
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    source = db.Column(db.String(30), default="trade_fee")  # trade_fee (ممكن نضيف مصادر تانية بعدين)
    trade_id = db.Column(db.Integer, db.ForeignKey("trade.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    trade = db.relationship("Trade")


class LoanRequest(db.Model):
    """طلب دين: أي مستخدم يقدر يطلبه، والأدمن بيوافق أو يرفض. لما يوافق، بيتحدد مدة السداد ونسبة الفايدة،
    وبعدين المستخدم يقدر يسدد من رصيده والمبلغ (أصل + فايدة) بيروح لخزينة GNID."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(500), default="")
    term_days = db.Column(db.Integer, default=3)      # مدة السداد المختارة (3/5/7 أيام)
    interest_pct = db.Column(db.Float, default=5)      # نسبة الفايدة المرتبطة بالمدة دي
    repay_amount = db.Column(db.Float)                 # أصل المبلغ + الفايدة (بيتحدد وقت الموافقة)
    due_date = db.Column(db.DateTime)                  # بيتحدد وقت الموافقة = تاريخها + المدة
    status = db.Column(db.String(20), default="pending")  # pending / approved / rejected / repaid
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    handled_at = db.Column(db.DateTime)
    handled_by = db.Column(db.String(80))
    repaid_at = db.Column(db.DateTime)
    reminder_sent = db.Column(db.Boolean, default=False)  # اتبعت تنبيه "باقي يوم" ولا لأ (عشان منبعتوش أكتر من مرة)
    user = db.relationship("User")


class CompanyRequest(db.Model):
    """طلب تسجيل شركة/مصنع جوه اللعبة كسهم متداول في السوق. المستخدم بيبعت بيانات مصنعه
    (رابط، مستوى، رأس المال، الإنتاج اليومي)، والأدمن بيوافق أو يرفض. لما يوافق، بيتحسب
    تقييم الشركة تلقائي وبيتعمل سهم جديد بالتقسيم: 50% مالك / 10% GNID / 40% متاح للسوق."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    company_name = db.Column(db.String(120), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    factory_link = db.Column(db.String(500), nullable=False)
    level = db.Column(db.Integer, nullable=False)
    capital = db.Column(db.Float, nullable=False)          # رأس المال/الكاش الحالي في المصنع
    daily_production = db.Column(db.Float, nullable=False)  # الإنتاج اليومي
    computed_valuation = db.Column(db.Float)                # بيتحسب وقت الموافقة
    status = db.Column(db.String(20), default="pending")    # pending / approved / rejected
    reject_reason = db.Column(db.String(300), default="")
    stock_id = db.Column(db.Integer, db.ForeignKey("stock.id"))  # السهم اللي اتعمل لو اتوافق عليه
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    handled_at = db.Column(db.DateTime)
    handled_by = db.Column(db.String(80))
    user = db.relationship("User")
    stock = db.relationship("Stock")


class CurrencyRequest(db.Model):
    """طلب إصدار عملة خاصة من لاعب - بيبعت تقرير عن العملة (اسم، رمز، وصف/تقرير)، والأدمن
    بيراجع البروفايل ويوافق أو يرفض. لما يوافق، بيحدد سعر الإصدار وإجمالي عدد الوحدات،
    وبيتعمل سهم جديد (asset_type='currency') وكل الوحدات بتروح لصاحب الطلب (100% ملكية بداية)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    currency_name = db.Column(db.String(120), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    report_text = db.Column(db.Text, nullable=False)  # تقرير المستخدم عن عملته - السند الاقتصادي/الغرض منها
    status = db.Column(db.String(20), default="pending")  # pending / approved / rejected
    reject_reason = db.Column(db.String(300), default="")
    stock_id = db.Column(db.Integer, db.ForeignKey("stock.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    handled_at = db.Column(db.DateTime)
    handled_by = db.Column(db.String(80))
    user = db.relationship("User")
    stock = db.relationship("Stock")


class DividendPayout(db.Model):
    """توزيع أرباح أسبوعي لشركة معينة - الأدمن بيدخل صافي الربح يدوي، والنظام بيحسب صندوق
    الأرباح (صافي الربح × نسبة الأرباح) ويوزعه بالتناسب على أكبر 5 مساهمين بالكمية.
    نفس الجدول ده بيتستخدم كمان لتوزيعات إيراد العملات (asset_type == 'currency')، بس
    بمعادلة تقسيم مختلفة (شايف admin_currency_distribute) - owner_amount بيبقى 0 دايمًا
    لتوزيعات الشركات العادية، وبيتسجل فيه نصيب صاحب العملة في توزيعات العملات."""
    id = db.Column(db.Integer, primary_key=True)
    stock_id = db.Column(db.Integer, db.ForeignKey("stock.id"), nullable=False)
    net_profit = db.Column(db.Float, nullable=False)      # صافي الربح اللي دخله الأدمن
    dividend_pct = db.Column(db.Float, nullable=False)     # نسبة الأرباح وقت التوزيع ده (بتتسجل تاريخيًا حتى لو اتغيرت بعدين)
    total_fund = db.Column(db.Float, nullable=False)       # صندوق الأرباح = صافي الربح × النسبة
    recipients_count = db.Column(db.Integer, default=0)
    admin_username = db.Column(db.String(80), default="")
    owner_amount = db.Column(db.Float, default=0)  # نصيب صاحب العملة المباشر (توزيعات العملات بس)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    stock = db.relationship("Stock")


class DividendRecipient(db.Model):
    """نصيب كل مساهم من توزيع أرباح معين - سجل تاريخي يوضح كل حد أخد قد إيه ومقابل كام سهم."""
    id = db.Column(db.Integer, primary_key=True)
    payout_id = db.Column(db.Integer, db.ForeignKey("dividend_payout.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    shares_at_time = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payout = db.relationship("DividendPayout")
    user = db.relationship("User")


class AdminActionLog(db.Model):
    """سجل دائم لإجراءات الأدمن/المشرف الحساسة - عشان يبقى فيه شفافية وواضح مين اللي عمل إيه (أدمن ولا مشرف)."""
    id = db.Column(db.Integer, primary_key=True)
    admin_username = db.Column(db.String(80), nullable=False)
    actor_role = db.Column(db.String(10), default="admin")  # admin / mod - محفوظة وقت الإجراء نفسه
    action = db.Column(db.String(30), nullable=False)  # balance_add / balance_subtract / password_change / user_delete / ...
    target_username = db.Column(db.String(80), default="")  # نص ثابت عشان يفضل واضح حتى لو الحساب اتحذف
    target_account_id = db.Column(db.String(20), default="")
    amount = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Holding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    stock_id = db.Column(db.Integer, db.ForeignKey("stock.id"), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    user = db.relationship("User")
    stock = db.relationship("Stock")
    __table_args__ = (db.UniqueConstraint("user_id", "stock_id"),)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    stock_id = db.Column(db.Integer, db.ForeignKey("stock.id"), nullable=False)
    side = db.Column(db.String(4), nullable=False)
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(10), default="open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User")
    stock = db.relationship("Stock")


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Vault(db.Model):
    """
    حساب الخزنة اللي المستخدمين بيحولّوا فلوس اللعبة عليه.
    نفس فكرة بوتك: بنراقب رصيد الخزنة، ولو زاد بنفك تشفير المبلغ
    (المبلغ = النقاط × DEPOSIT_UNIT + account_id) ونضيف الرصيد للمستخدم صاحب الآي دي.
    """
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(500), default="")
    player_id = db.Column(db.String(50), default="")
    account_name = db.Column(db.String(120), default="")  # اسم حساب الخزنة داخل اللعبة (يظهر للمستخدمين)
    account_url = db.Column(db.String(500), default="")   # رابط اختياري لصفحة الحساب داخل اللعبة
    last_balance = db.Column(db.BigInteger, default=0)
    healthy = db.Column(db.Boolean, default=True)
    notified_broken = db.Column(db.Boolean, default=False)  # مش مستخدم دلوقتي (إشعارات التوكن اتشالت بناءً على طلبك)
    updated_at = db.Column(db.DateTime)


class MigrationFlag(db.Model):
    """علامة صغيرة عشان نتأكد إن أي تعديل بيانات لمرة واحدة بس (زي إلغاء أوامر البيع القديمة عند تحديث معين)
    ما يتكررش تاني في كل مرة السيرفر بيشتغل فيها."""
    key = db.Column(db.String(80), primary_key=True)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow)


class Deposit(db.Model):
    """سجل عمليات الإيداع - محلولة تلقائي أو محتاجة مراجعة يدوية"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    delta = db.Column(db.BigInteger, nullable=False)
    amount_credited = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default="confirmed")  # confirmed / pending_review
    note = db.Column(db.String(255))
    external_id = db.Column(db.String(64))  # آي دي حركة التحويل نفسها جوه اللعبة - بيمنعنا نعالج نفس التحويل مرتين
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User")


class Investment(db.Model):
    """استثمار تلقائي: المستخدم بيودع مبلغ، وبعد مدة ثابتة بياخد المبلغ + نسبة أرباح ثابتة تلقائيًا."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    rate_percent = db.Column(db.Float, nullable=False)
    payout = db.Column(db.Float, nullable=False)  # amount + الأرباح
    status = db.Column(db.String(20), default="active")  # active / paid
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    matures_at = db.Column(db.DateTime, nullable=False)
    paid_at = db.Column(db.DateTime)
    is_manual = db.Column(db.Boolean, default=False)   # اتضاف يدويًا من الأدمن/المشرف ولا اتعمل من المستخدم نفسه
    creator_username = db.Column(db.String(80))        # مين ضافه لو كان يدوي
    creator_role = db.Column(db.String(10))             # admin / mod - لو كان يدوي
    user = db.relationship("User")


class WithdrawalRequest(db.Model):
    """طلب سحب: المستخدم بيبعت رابط حسابه داخل اللعبة، الأدمن بيحول له يدويًا وبعدين يعمل تم للطلب."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    account_link = db.Column(db.String(500), nullable=False)
    account_name = db.Column(db.String(120), default="")  # اسم الحساب داخل اللعبة (اختياري، بيسهّل التعرف عليه)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending / done / rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    handled_at = db.Column(db.DateTime)
    handled_by = db.Column(db.String(80))
    user = db.relationship("User")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ============================================================
# نظام الخزنة (Vault) - إيداع تلقائي من داخل اللعبة، زي بوتك بالظبط
# ============================================================

def _game_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }


def extract_player_numeric_id(link):
    """بيطلع رقم اللاعب (الآي دي الظاهر في الرابط) من رابط بروفايله في اللعبة.
    بيدعم أشكال زي /profile/player/123 أو /press/player/123."""
    if not link:
        return None
    m = re.search(r"/player/(\d+)", link)
    return m.group(1) if m else None


def resolve_player_uuid(numeric_id, token):
    """بياخد رقم اللاعب الظاهر ويرجع الـ UUID الحقيقي بتاعه من اللعبة - مطلوب عشان نقدر نحوله فلوس.
    بيرجع (uuid, username) أو (None, None) لو فشل."""
    try:
        r = requests.get(f"{GAME_API_BASE}/players/{numeric_id}",
                          headers=_game_headers(token), timeout=15)
        if r.status_code != 200:
            return None, None
        data = r.json()
        player = data.get("player", data) if isinstance(data, dict) else {}
        uuid = player.get("id")
        username = player.get("username")
        return (uuid, username) if uuid else (None, None)
    except Exception as e:
        log.error(f"فشل جلب بيانات اللاعب رقم {numeric_id}: {e}")
        return None, None


def send_game_transfer(token, recipient_uuid, amount):
    """بيبعت تحويل فعلي داخل اللعبة لحساب معين عن طريق الـ UUID بتاعه.
    بيرجع dict فيه {"ok": True, ...بيانات الرد} أو {"ok": False, "error": "..."}"""
    try:
        r = requests.post(
            f"{GAME_API_BASE}/transfer/send",
            headers=_game_headers(token),
            json={"recipient_id": recipient_uuid, "amount": int(amount)},
            timeout=20,
        )
        try:
            data = r.json()
        except Exception:
            data = {}
        if r.status_code == 200 and data.get("success"):
            return {"ok": True, **data}
        return {"ok": False, "error": data.get("message") or data.get("error") or f"HTTP {r.status_code}"}
    except Exception as e:
        log.error(f"فشل تنفيذ تحويل داخل اللعبة: {e}")
        return {"ok": False, "error": str(e)}


def fetch_vault_economy_history(token, page=1, limit=50):
    """بيجيب سجل حركات حساب الخزنة (التحويلات الداخلة والخارجة) مباشرة من اللعبة عن طريق توكن الخزنة.
    بيرجع (entries, error) - entries عبارة عن list من dicts منظّفة، أو ([], "رسالة الخطأ") لو فشل."""
    try:
        r = requests.get(
            f"{GAME_API_BASE}/players/economy-history",
            headers=_game_headers(token),
            params={"page": page, "limit": limit, "categories": "transfer_in,transfer_out"},
            timeout=20,
        )
        if r.status_code != 200:
            return [], f"HTTP {r.status_code}"
        data = r.json()
    except Exception as e:
        log.error(f"فشل جلب سجل حركات الخزنة: {e}")
        return [], str(e)

    entries = []
    for log_item in data.get("logs", []):
        created_at_raw = log_item.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except Exception:
            created_at = None
        meta_ref = log_item.get("meta_ref") or {}
        dp = meta_ref.get("dp") or {}
        counterparty_name = meta_ref.get("name") or dp.get("name") or "—"
        counterparty_id = meta_ref.get("id")
        entries.append({
            "id": log_item.get("id"),
            "type": log_item.get("type"),  # income / expense
            "category": log_item.get("category"),  # transfer_in / transfer_out
            "amount": log_item.get("amount", 0),
            "created_at": created_at,
            "description": log_item.get("description", ""),
            "counterparty_name": counterparty_name,
            "counterparty_id": counterparty_id,
        })
    return entries, None


def decode_deposit(delta):
    """
    يفك مبلغ التحويل لـ (account_id, credited_amount).
    المستخدم بيبعت: (الرصيد اللي عايز يضيفه) + آي دي حسابه.
    مثال: عايز يضيف 5000 وآي دي حسابه '2' → يبعت 5002، وده بيتفك لـ account_id='2', credited=5000.
    """
    if delta <= 0:
        return None, 0
    account_id = delta % DEPOSIT_UNIT
    credited_amount = delta - account_id
    if credited_amount <= 0:
        return None, 0
    return str(account_id), credited_amount


def check_vault_deposits():
    """بتتنفذ كل دقيقة: تجيب آخر حركات حساب الخزنة (داخلة وخارجة) من اللعبة مباشرة،
    وتعالج كل تحويل داخل (transfer_in) جديد لوحده بشكل مستقل.

    ملحوظة مهمة: قبل كده كانت الطريقة إنها تجيب رصيد الخزنة الإجمالي دلوقتي وتقارنه
    بآخر رصيد محفوظ، وتحسب الفرق (delta) كإنه "الإيداع الجديد". المشكلة إن ده بيفترض
    إن مفيش غير تحويل واحد بس حصل في نفس الدقيقة. لو حصل أي تحويل خارج (سحب، تحويل
    أدمن، إلخ) في نفس الدقيقة اللي وصل فيها إيداع حقيقي، صافي الفرق كان بيبقى غلط
    تمامًا (ممكن يبقى سالب فيتم تجاهل الإيداع بالكامل من غير ما حد يلاحظ، أو يبقى رقم
    مختلط بين أكتر من عملية فيفتكر آي دي غلط). دلوقتي بنعالج كل حركة داخلة لوحدها من
    سجل الحركات نفسه (فيه آي دي فريد لكل حركة)، فمفيش أي تأثير من أي حركة خارجة أو
    داخلة تانية بتحصل في نفس الوقت."""
    with app.app_context():
        try:
            vault = Vault.query.get(1)
            if not vault or not vault.token:
                return

            # لسه بنجيب البروفايل عشان نعرض رصيد الخزنة الحالي في لوحة الخزينة ونتأكد
            # إن التوكن لسه شغال - مش بنستخدمه في حساب الإيداعات تاني.
            r = requests.get(f"{GAME_API_BASE}/players/profile",
                              headers=_game_headers(vault.token), timeout=15)
            if r.status_code not in (200, 304):
                vault.healthy = False
                db.session.commit()
                log.warning(f"توكن الخزنة توقف عن العمل ({r.status_code})")
                return

            if r.content:
                data = r.json()
                p = data.get("player", data) if isinstance(data, dict) else {}
                vault.last_balance = int(p.get("balance", 0) or 0)
            vault.healthy = True
            vault.updated_at = datetime.utcnow()
            db.session.commit()

            entries, err = fetch_vault_economy_history(vault.token, page=1, limit=50)
            if err:
                return

            # ترقية لمرة واحدة بس: النظام القديم كان بيحسب "الفرق الكلي في الرصيد" مش
            # حركة حركة، فمفيش عندنا external_id متسجل لأي حركة قديمة اتعالجت قبل كده.
            # لو دي أول مرة الكود الجديد بيشتغل (مفيش ولا Deposit واحد متسجل عليه
            # external_id لسه)، بنسجل آي ديهات كل الحركات الداخلة الحالية كـ"شوفناها"
            # من غير ما نضيف رصيد لحد - عشان منكررش إضافة فلوس اتضافت بالفعل قبل كده.
            # أي حركة جديدة بعد اللحظة دي هتتعالج طبيعي.
            is_first_run_of_new_system = Deposit.query.filter(Deposit.external_id.isnot(None)).first() is None
            if is_first_run_of_new_system:
                for entry in entries:
                    if entry.get("category") != "transfer_in":
                        continue
                    ext_id = str(entry.get("id")) if entry.get("id") is not None else None
                    if not ext_id:
                        continue
                    db.session.add(Deposit(user_id=None, delta=int(entry.get("amount") or 0), amount_credited=0,
                                            status="confirmed", external_id=ext_id,
                                            note="ترقية النظام - حركة قديمة اتعالجت بالطريقة القديمة قبل كده، اتسجلت هنا بس عشان منكررش معالجتها"))
                db.session.commit()
                return

            # من الأقدم للأحدث عشان لو فيه أكتر من إيداع جديد، يتسجلوا بترتيبهم الصحيح
            new_entries = [e for e in reversed(entries) if e.get("category") == "transfer_in"]
            for entry in new_entries:
                ext_id = str(entry.get("id")) if entry.get("id") is not None else None
                if not ext_id:
                    continue
                if Deposit.query.filter_by(external_id=ext_id).first():
                    continue  # اتعالجت قبل كده

                amount = int(entry.get("amount") or 0)
                if amount <= 0:
                    continue
                account_id, credited_amount = decode_deposit(amount)
                user = User.query.filter_by(account_id=account_id).first() if account_id else None

                if user and credited_amount > 0:
                    user.balance += credited_amount
                    db.session.add(Deposit(user_id=user.id, delta=amount, amount_credited=credited_amount,
                                            status="confirmed", external_id=ext_id,
                                            note=f"إيداع تلقائي - خزنة {vault.player_id}"))
                    log.info(f"إيداع تلقائي: {credited_amount} لـ {user.username} (amount={amount})")
                else:
                    # فلوس وصلت فعليًا للخزنة بس مش متربطة بحساب واضح (آي دي غلط أو ناقص) -
                    # بدل ما تفضل عالقة في الخزنة، بنحاول نرجعها تلقائيًا لنفس الشخص اللي
                    # بعتها (بنفس الطريقة اللي بيتبعت بيها فلوس السحب بالظبط). لو الإرجاع
                    # فشل لأي سبب (مفيش آي دي واضح للمرسل، أو مشكلة في اللعبة وقت التنفيذ)،
                    # بنسجلها كـ pending_review عشان الأدمن يراجعها يدويًا بدل ما تتجاهل بصمت.
                    sender_name = entry.get("counterparty_name")
                    sender_uuid = entry.get("counterparty_id")
                    refunded = False
                    refund_error = None
                    if sender_uuid:
                        result = send_game_transfer(vault.token, sender_uuid, amount)
                        if result.get("ok"):
                            refunded = True
                        else:
                            refund_error = result.get("error")
                    else:
                        refund_error = "مفيش آي دي واضح للمرسل في سجل الحركة"

                    if refunded:
                        note = f"إيداع بقيمة {amount} مش متربط بأي حساب - اترجعت الفلوس تلقائيًا لصاحبها"
                        if sender_name:
                            note += f" ({sender_name})"
                        if account_id:
                            note += f" - الآي دي المفكوك من المبلغ: {account_id} (مفيش حساب بالآي دي ده)"
                        db.session.add(Deposit(user_id=None, delta=amount, amount_credited=0,
                                                status="refunded", external_id=ext_id, note=note))
                        log.info(f"إيداع غير معروف بقيمة {amount} اترجع تلقائيًا للمرسل ({sender_name or 'مش معروف'})")
                    else:
                        note = f"إيداع غير معروف بقيمة {amount} - محتاج مراجعة يدوية (فشل الإرجاع التلقائي: {refund_error})"
                        if sender_name:
                            note += f" - المرسل: {sender_name}"
                        if account_id:
                            note += f" (الآي دي المفكوك من المبلغ: {account_id} - مفيش حساب بالآي دي ده)"
                        db.session.add(Deposit(user_id=None, delta=amount, amount_credited=0,
                                                status="pending_review", external_id=ext_id, note=note))
                        log.warning(f"إيداع غير معروف بقيمة {amount} - فشل الإرجاع التلقائي ({refund_error}) - اتسجل للمراجعة اليدوية (مرسل: {sender_name or 'مش معروف'})")

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            log.error(f"check_vault_deposits err: {e}")
        finally:
            db.session.remove()


# ============================================================
# Templates (كلها هنا كـ strings بدل مجلد templates/)
# ============================================================

BASE = """
<!DOCTYPE html>
<html lang="{{ session.get('lang','ar') }}" dir="{{ 'rtl' if session.get('lang','ar') == 'ar' else 'ltr' }}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="{{ csrf_token() }}">
<title>{{ tr('brand') }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
/* =========================================================
   GNID BANK — نظام تصميم موحّد (نسخة منقّحة)
   نفس الهوية: ليلي غامق + ذهبي، بس بتباعد وتباين وهرم أوضح.
   ========================================================= */

:root {
  /* ألوان */
  --bg: #0A0E13;
  --bg-soft: #0E141B;
  --panel: #121923;
  --panel-raised: #18212D;
  --panel-hover: #1D2836;
  --line: #232F3E;
  --line-soft: #1A2430;
  --gold: #D2AC5A;
  --gold-soft: rgba(210,172,90,0.10);
  --gold-dim: #8A7238;
  --ink: #ECE8DD;
  --ink-dim: #93A1B4;
  --ink-faint: #6C7A8C;
  --green: #4E9070;
  --green-ink: #7BD7A8;
  --red: #B45344;
  --red-ink: #FF9187;

  /* سلّم مسافات */
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 20px; --s6: 24px; --s8: 32px;

  /* أنصاف أقطار */
  --r-sm: 8px; --r-md: 10px; --r-lg: 14px; --r-pill: 999px;

  /* ظلال */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.30);
  --shadow-md: 0 6px 20px rgba(0,0,0,0.28);
  --shadow-lg: 0 18px 44px rgba(0,0,0,0.55);

  /* خطوط */
  --font-sans: 'Cairo', system-ui, sans-serif;
  --font-mono: 'IBM Plex Mono', ui-monospace, monospace;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  background-image:
    radial-gradient(120% 60% at 50% -10%, rgba(210,172,90,0.07), transparent 60%),
    linear-gradient(rgba(210,172,90,0.016) 1px, transparent 1px),
    linear-gradient(90deg, rgba(210,172,90,0.016) 1px, transparent 1px);
  background-size: auto, 48px 48px, 48px 48px;
  color: var(--ink);
  font-family: var(--font-sans);
  min-height: 100vh;
  line-height: 1.6;
  scroll-behavior: smooth;
  -webkit-text-size-adjust: 100%;
  -webkit-font-smoothing: antialiased;
}

::selection { background: rgba(210,172,90,0.28); }

/* سكرول بار أهدى */
* { scrollbar-width: thin; scrollbar-color: var(--line) transparent; }
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-thumb { background: var(--line); border-radius: 999px; }

.wrap { max-width: 900px; margin: 0 auto; padding: 0 var(--s5) 72px; }

/* ---------- Header / Ledger bar ---------- */
.ledger-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  margin: var(--s3) 0 var(--s8);
  background: color-mix(in srgb, var(--panel) 97%, transparent);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-sm);
  flex-wrap: wrap;
  position: sticky;
  top: var(--s2);
  z-index: 70;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--s2);
  font-weight: 900;
  font-size: 18px;
  letter-spacing: 0.4px;
  color: var(--gold);
}
.brand .seal {
  width: 28px; height: 28px;
  border-radius: 50%;
  object-fit: cover;
  display: block;
  border: 1px solid rgba(210,172,90,0.35);
}

.notif-bell {
  position: relative;
  display: inline-flex; align-items: center; justify-content: center;
  width: 40px; height: 40px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line);
  background: var(--panel-raised);
  font-size: 16px;
  text-decoration: none;
  flex-shrink: 0;
  transition: border-color .15s, background .15s;
}
.notif-bell:hover { border-color: var(--gold-dim); background: var(--panel-hover); }
.notif-badge {
  position: absolute; top: -6px; inset-inline-end: -6px;
  background: var(--red); color: #fff;
  font-size: 10px; font-weight: 800;
  min-width: 18px; height: 18px; padding: 0 4px;
  border-radius: var(--r-pill);
  display: flex; align-items: center; justify-content: center;
  line-height: 1;
  border: 2px solid var(--bg);
}

.id-chip {
  font-family: var(--font-mono);
  font-weight: 600;
  background: var(--panel-raised);
  border: 1px solid var(--line);
  color: var(--ink-dim);
  padding: 9px 14px;
  border-radius: var(--r-sm);
  font-size: 12.5px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.id-chip b { color: var(--gold); }

.nav-wrapper { position: relative; }
.nav-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--s2);
  min-height: 44px;
  color: var(--gold);
  background: linear-gradient(180deg, rgba(210,172,90,0.10), rgba(210,172,90,0.03));
  border: 1px solid var(--gold-dim);
  padding: 10px 18px;
  border-radius: var(--r-sm);
  font-weight: 700;
  font-size: 14px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: background .15s, border-color .15s;
}
.nav-toggle:hover { background: rgba(210,172,90,0.14); border-color: var(--gold); }

.nav-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(5,7,10,0.62);
  backdrop-filter: blur(2px);
  opacity: 0;
  visibility: hidden;
  transition: opacity .18s ease, visibility .18s ease;
  z-index: 55;
}
.nav-backdrop.open { opacity: 1; visibility: visible; }

.nav {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
  position: absolute;
  top: calc(100% + 10px);
  inset-inline-start: 0;
  min-width: 260px;
  max-height: 74vh;
  overflow-y: auto;
  overscroll-behavior: contain;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  padding: var(--s2);
  z-index: 80;
  box-shadow: var(--shadow-lg);
  opacity: 0;
  visibility: hidden;
  transform: translateY(-6px) scale(0.985);
  transform-origin: top;
  transition: opacity .16s ease, transform .16s ease, visibility .16s ease;
  pointer-events: none;
}
.nav.open { opacity: 1; visibility: visible; transform: none; pointer-events: auto; }
.nav a {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-height: 44px;
  color: var(--ink-dim);
  text-decoration: none;
  font-weight: 700;
  font-size: 13.5px;
  padding: 10px 12px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line-soft);
  background: var(--panel-raised);
  transition: color .15s, background .15s, border-color .15s;
}
.nav a:hover, .nav a:focus-visible { color: var(--gold); background: var(--panel-hover); border-color: var(--gold-dim); outline: none; }
.nav a.nav-admin { border-inline-start: 3px solid var(--gold-dim); }
.nav a.nav-admin:hover { border-inline-start-color: var(--gold); }
.nav a.nav-logout { margin-top: var(--s2); border-color: rgba(180,83,68,0.35); color: #d9a49c; }
.nav a.nav-logout:hover { color: var(--red-ink); background: rgba(180,83,68,0.14); border-color: var(--red); }
.nav-section-label {
  color: var(--ink-faint);
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  padding: var(--s3) var(--s2) var(--s1);
  border-top: 1px solid var(--line);
  margin-top: var(--s2);
}
.nav-section-label:first-child { border-top: none; margin-top: 0; }

.balance-chip {
  font-family: var(--font-mono);
  font-weight: 600;
  background: linear-gradient(180deg, rgba(210,172,90,0.12), rgba(210,172,90,0.03));
  border: 1px solid var(--gold-dim);
  color: var(--gold);
  padding: 9px 16px;
  border-radius: var(--r-sm);
  font-size: 14px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.lang-switch-wrapper { position: relative; }
.id-lang-row { display: flex; align-items: center; gap: var(--s2); flex-wrap: wrap; }
.lang-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 40px;
  color: var(--ink-dim);
  background: var(--panel-raised);
  border: 1px solid var(--line);
  padding: 8px 14px;
  border-radius: var(--r-sm);
  font-weight: 700;
  font-size: 12.5px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: color .15s, border-color .15s, background .15s;
}
.lang-toggle:hover { color: var(--gold); border-color: var(--gold-dim); background: var(--panel-hover); }
.lang-switch {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
  font-family: var(--font-mono);
  font-size: 12px;
  position: absolute;
  top: calc(100% + 8px);
  inset-inline-end: 0;
  min-width: 160px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: var(--s2);
  z-index: 80;
  box-shadow: var(--shadow-lg);
  opacity: 0;
  visibility: hidden;
  transform: translateY(-6px);
  transition: opacity .15s ease, transform .15s ease, visibility .15s ease;
  pointer-events: none;
}
.lang-switch.open { opacity: 1; visibility: visible; transform: none; pointer-events: auto; }
.lang-switch a {
  color: var(--ink-dim);
  text-decoration: none;
  padding: 9px 10px;
  border-radius: 6px;
  border: 1px solid var(--line-soft);
  transition: color .15s, border-color .15s, background .15s;
}
.lang-switch a:hover { color: var(--gold); border-color: var(--gold-dim); background: var(--panel-hover); }
.lang-switch a.active { color: var(--gold); border-color: var(--gold); background: var(--gold-soft); }

/* ---------- Flash messages ---------- */
.flash-stack {
  list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--s2);
  position: fixed; top: 14px; left: 50%; transform: translateX(-50%);
  z-index: 9999; width: calc(100% - 28px); max-width: 460px;
}
.flash-stack li {
  background: var(--panel-raised);
  border: 1px solid var(--line);
  border-inline-start: 3px solid var(--gold);
  padding: 13px 42px 13px 16px;
  border-radius: var(--r-md);
  font-size: 13.5px;
  line-height: 1.5;
  color: var(--ink);
  box-shadow: var(--shadow-md);
  position: relative;
  animation: flash-in 0.25s ease-out;
}
.flash-stack li.flash-hide { animation: flash-out 0.25s ease-in forwards; }
.flash-close {
  position: absolute; top: 6px; inset-inline-end: 8px;
  background: none; border: none; color: var(--ink-faint); font-size: 18px;
  line-height: 1; cursor: pointer; padding: 6px 8px; min-height: 0;
}
.flash-close:hover { color: var(--ink); }
@keyframes flash-in { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes flash-out { from { opacity: 1; } to { opacity: 0; transform: translateY(-8px); } }

/* ---------- Admin users: search + collapsible rows ---------- */
[hidden] { display: none !important; }
.user-toggle {
  background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  color: var(--gold); font-size: 12px; padding: 3px 9px; margin-inline-end: var(--s2);
  cursor: pointer; line-height: 1.4;
}
.user-toggle:hover { border-color: var(--gold); }

/* ---------- Cards / panels ---------- */
.panel {
  background: var(--panel);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-lg);
  padding: var(--s6);
  margin-bottom: var(--s5);
  box-shadow: var(--shadow-sm);
  overflow-x: auto;
}
.card {
  background: var(--panel-raised);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-md);
}
.panel h2 {
  margin: 0 0 var(--s4);
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 1.6px;
  color: var(--gold);
  font-weight: 800;
}
.panel h3 {
  margin: var(--s6) 0 var(--s3);
  font-size: 13.5px;
  color: var(--ink);
  font-weight: 800;
  border-top: 1px solid var(--line-soft);
  padding-top: var(--s5);
}
.panel > p.lede {
  margin: calc(var(--s3) * -1) 0 var(--s5);
  font-size: 13px;
  color: var(--ink-dim);
  max-width: 62ch;
}

/* ---------- Forms ---------- */
form { display: flex; flex-direction: column; gap: var(--s3); max-width: 440px; }
form.inline { flex-direction: row; flex-wrap: wrap; align-items: center; gap: var(--s2); max-width: none; }

label { font-size: 12.5px; color: var(--ink-dim); font-weight: 700; }

form:not(.inline) > div { display: flex; flex-direction: column; gap: 6px; }
form:not(.inline) > div > input,
form:not(.inline) > div > select,
form:not(.inline) > div > textarea { width: 100%; box-sizing: border-box; }

input, select, textarea {
  background: var(--bg-soft);
  border: 1px solid var(--line);
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 14px;
  min-height: 44px;
  padding: 11px 13px;
  border-radius: var(--r-sm);
  outline: none;
  transition: border-color .15s, box-shadow .15s, background .15s;
}
input:hover, select:hover, textarea:hover { border-color: #2E3D50; }
textarea { font-family: var(--font-sans); resize: vertical; min-height: 84px; line-height: 1.6; }
input::placeholder, textarea::placeholder { color: var(--ink-faint); font-family: var(--font-sans); }
input:focus, select:focus, textarea:focus,
input:focus-visible, select:focus-visible, textarea:focus-visible {
  border-color: var(--gold);
  box-shadow: 0 0 0 3px rgba(210,172,90,0.14);
  background: var(--panel-raised);
}
input[type="checkbox"], input[type="radio"] { min-height: 0; accent-color: var(--gold); }

button, .btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: var(--gold);
  color: #14100A;
  border: 1px solid transparent;
  font-family: var(--font-sans);
  font-weight: 800;
  font-size: 14px;
  min-height: 44px;
  padding: 11px 20px;
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: filter .15s, transform .08s, background .15s, border-color .15s;
  align-self: flex-start;
  white-space: nowrap;
}
button:hover, .btn:hover { filter: brightness(1.08); }
button:active { transform: translateY(1px); }
button:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
button:disabled { opacity: .5; cursor: not-allowed; filter: none; }

button.secondary {
  background: var(--panel-raised);
  color: var(--ink);
  border-color: var(--line);
}
button.secondary:hover { background: var(--panel-hover); border-color: var(--gold-dim); filter: none; }

button.danger { background: transparent; border-color: var(--red); color: var(--red-ink); }
button.danger:hover { background: rgba(180,83,68,0.14); filter: none; }

button.buy { background: var(--green); color: #06120C; }
button.sell { background: var(--red); color: #1A0D0B; }

.auth-link {
  font-size: 13px;
  color: var(--ink-dim);
}
.auth-link a { color: var(--gold); text-decoration: none; font-weight: 700; }
.auth-link a:hover { text-decoration: underline; }

/* ---------- Auth hero (login/register) ---------- */
.auth-hero {
  text-align: center;
  padding: var(--s8) var(--s4) var(--s6);
}
.auth-seal {
  width: 86px;
  height: 86px;
  margin: 0 auto var(--s4);
  border-radius: 50%;
  display: block;
  object-fit: cover;
  filter: drop-shadow(0 0 22px rgba(210,172,90,0.28));
}
.auth-title {
  font-size: 27px;
  font-weight: 900;
  letter-spacing: 1px;
  color: var(--gold);
  margin-bottom: 6px;
}
.auth-tagline {
  color: var(--ink-dim);
  font-size: 13.5px;
  max-width: 380px;
  margin: 0 auto;
}
.auth-footer-links {
  display: flex;
  justify-content: center;
  gap: var(--s2);
  flex-wrap: wrap;
  padding-bottom: var(--s8);
}
.auth-footer-links a {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-dim);
  text-decoration: none;
  font-size: 13px;
  font-weight: 700;
  padding: 10px 18px;
  border-radius: var(--r-pill);
  border: 1px solid var(--line);
  background: var(--panel-raised);
  transition: color .15s, border-color .15s, background .15s;
}
.auth-footer-links a:hover { color: var(--gold); border-color: var(--gold-dim); background: var(--panel-hover); }

/* ---------- Auth v2 (premium) ---------- */
.auth-shell {
  max-width: 440px;
  margin: 0 auto;
  padding: var(--s6) 0 var(--s4);
}
.auth-shell .auth-hero { padding: var(--s4) var(--s3) var(--s5); }
.auth-shell .auth-seal {
  width: 96px; height: 96px;
  padding: 6px;
  background:
    linear-gradient(var(--panel), var(--panel)) padding-box,
    conic-gradient(from 210deg, var(--gold-dim), var(--gold), var(--gold-dim), #6b5726, var(--gold)) border-box;
  border: 2px solid transparent;
  box-shadow: 0 0 0 6px rgba(210,172,90,0.05), 0 18px 40px rgba(0,0,0,0.55);
  filter: none;
}
.auth-title { font-size: 30px; letter-spacing: 2.4px; }
.auth-rule {
  width: 118px; height: 1px; margin: var(--s3) auto var(--s3);
  background: linear-gradient(90deg, transparent, var(--gold-dim), transparent);
}

.auth-card {
  position: relative;
  background:
    radial-gradient(120% 80% at 50% -20%, rgba(210,172,90,0.09), transparent 62%),
    linear-gradient(180deg, color-mix(in srgb, var(--panel-raised) 92%, transparent), var(--panel));
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: var(--s6) var(--s5) var(--s5);
  box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(255,255,255,0.04);
  overflow: hidden;
}
.auth-card::before {
  content: "";
  position: absolute; top: 0; inset-inline: 12%;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--gold), transparent);
  opacity: .8;
}

.auth-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 4px;
  margin-bottom: var(--s5);
  background: var(--bg-soft);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-pill);
}
.auth-tabs a {
  text-align: center;
  padding: 10px 6px;
  font-size: 13px;
  font-weight: 800;
  text-decoration: none;
  color: var(--ink-dim);
  border-radius: var(--r-pill);
  transition: color .15s, background .15s;
}
.auth-tabs a:hover { color: var(--ink); }
.auth-tabs a.active {
  color: #14100A;
  background: linear-gradient(180deg, #E4C377, var(--gold));
  box-shadow: 0 4px 14px rgba(210,172,90,0.22);
}

.auth-card h2 { margin: 0 0 4px; font-size: 12px; }
.auth-card > p.lede { margin: 0 0 var(--s5); font-size: 12.5px; }
.auth-card form { max-width: none; gap: var(--s4); }
.auth-card label {
  display: block;
  font-size: 11px;
  letter-spacing: 1.1px;
  text-transform: uppercase;
  color: var(--ink-faint);
  margin-bottom: 6px;
}
.auth-card input {
  width: 100%;
  min-height: 50px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--bg) 88%, #000);
  font-size: 15px;
}
.auth-card input:focus {
  border-color: var(--gold);
  box-shadow: 0 0 0 3px rgba(210,172,90,0.14);
}
.auth-card button[type="submit"] {
  width: 100%;
  min-height: 52px;
  margin-top: var(--s2);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: .6px;
  border-radius: 12px;
}
.pw-field { position: relative; }
.pw-field input { padding-inline-end: 48px; }
.pw-toggle {
  position: absolute;
  inset-inline-end: 6px;
  bottom: 5px;
  width: 40px; height: 40px;
  min-height: 40px;
  display: flex; align-items: center; justify-content: center;
  background: transparent;
  border: none;
  color: var(--ink-faint);
  font-size: 15px;
  cursor: pointer;
  padding: 0;
}
.pw-toggle:hover { color: var(--gold); filter: none; }
.auth-note {
  display: flex; align-items: center; justify-content: center; gap: 6px;
  margin-top: var(--s4);
  font-size: 11.5px;
  color: var(--ink-faint);
}
@media (max-width: 480px) {
  .auth-title { font-size: 25px; }
  .auth-card { padding: var(--s5) var(--s4); border-radius: 16px; }
}


/* ---------- Tables ---------- */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td {
  text-align: start;
  padding: 11px 12px;
  border-bottom: 1px solid var(--line-soft);
}
th {
  color: var(--ink-faint);
  text-transform: uppercase;
  font-size: 10.5px;
  letter-spacing: 1.1px;
  font-weight: 800;
  white-space: nowrap;
}
td {
  color: var(--ink);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  overflow-wrap: break-word;
}
tr:last-child td { border-bottom: none; }
tbody tr { transition: background .12s; }
tr:nth-child(even) td { background: rgba(255,255,255,0.014); }
tr:hover td { background: rgba(210,172,90,0.05); }

.side-buy { color: var(--green-ink); font-weight: 700; }
.side-sell { color: var(--red-ink); font-weight: 700; }

/* ---------- Status pill ---------- */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--r-pill);
  font-weight: 700;
  font-size: 12.5px;
  min-height: 0;
}
button.status-pill { font-family: inherit; cursor: pointer; }
.status-pill.ok { background: rgba(78,144,112,0.16); border: 1px solid var(--green); color: var(--green-ink); }
.status-pill.bad { background: rgba(180,83,68,0.16); border: 1px solid var(--red); color: var(--red-ink); }
.status-pill.unknown { background: var(--panel-raised); border: 1px solid var(--line); color: var(--ink-dim); }

/* ---------- Chart range tabs ---------- */
.range-tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: var(--s4); }
.range-tab {
  background: var(--panel-raised);
  border: 1px solid var(--line);
  color: var(--ink-dim);
  padding: 7px 15px;
  min-height: 0;
  border-radius: var(--r-pill);
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: color .15s, border-color .15s, background .15s;
}
.range-tab:hover { color: var(--gold); border-color: var(--gold-dim); }
.range-tab.active { color: var(--gold); border-color: var(--gold); background: var(--gold-soft); }

/* ---------- Stock card grid ---------- */
.stock-card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--s3); }
.stock-card {
  background: var(--panel-raised);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-lg);
  padding: var(--s4);
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: border-color .15s, transform .12s, background .15s;
}
.stock-card:hover { border-color: var(--gold-dim); background: var(--panel-hover); transform: translateY(-1px); }
.stock-card-head { display: flex; align-items: center; gap: var(--s2); }
.stock-card-icon { font-size: 22px; }
.stock-card-name { color: var(--ink); font-weight: 800; text-decoration: none; font-size: 14px; }
.stock-card-name:hover { color: var(--gold); }
.stock-card-price {
  font-family: var(--font-mono); font-size: 20px; font-weight: 700; color: var(--gold);
  font-variant-numeric: tabular-nums; letter-spacing: -0.4px;
}
.stock-card-change { font-family: var(--font-mono); font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; }
.stock-card-meta {
  display: flex; flex-direction: column; gap: 6px;
  margin: var(--s2) 0; padding: var(--s3);
  background: var(--bg-soft); border: 1px solid var(--line-soft); border-radius: var(--r-sm);
}
.stock-card-meta-item { display: flex; justify-content: space-between; align-items: baseline; gap: var(--s2); }
.stock-card-meta-label { font-size: 12px; color: var(--ink-dim); }
.stock-card-meta-value { font-family: var(--font-mono); font-size: 13.5px; font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums; }
.stock-card-buy-form { display: flex; gap: 6px; margin-top: var(--s1); }
.stock-card-buy-form input { flex: 1; min-width: 0; padding: 9px 10px; font-size: 13px; min-height: 40px; }
.stock-card-buy-form button { padding: 9px 14px; font-size: 13px; min-height: 40px; }

/* ---------- Dashboard greeting + profile nudge ---------- */
.dash-greeting { margin: 0 0 var(--s5); }
.dash-greeting h1 { margin: 0 0 var(--s1); font-size: 24px; font-weight: 900; color: var(--ink); letter-spacing: -0.2px; }
.dash-greeting p { margin: 0; color: var(--ink-faint); font-size: 12.5px; font-family: var(--font-mono); }

.profile-nudge {
  display: flex;
  align-items: center;
  gap: var(--s3);
  background: linear-gradient(135deg, rgba(210,172,90,0.09), var(--panel-raised));
  border: 1px solid var(--gold-dim);
  border-radius: var(--r-lg);
  padding: var(--s4);
  margin-bottom: var(--s5);
  text-decoration: none;
  transition: border-color .15s, background .15s;
}
.profile-nudge:hover { border-color: var(--gold); }
.profile-nudge-icon { font-size: 22px; flex-shrink: 0; }
.profile-nudge-text { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.profile-nudge-text b { color: var(--ink); font-size: 14px; }
.profile-nudge-text span { color: var(--ink-dim); font-size: 12px; }
.profile-nudge-arrow { color: var(--gold); font-size: 22px; flex-shrink: 0; }
.verified-badge { font-size: 12px; vertical-align: middle; }

.nav-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 19px;
  height: 19px;
  padding: 0 6px;
  margin-inline-start: 6px;
  border-radius: var(--r-pill);
  background: var(--red);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  font-family: var(--font-mono);
  vertical-align: middle;
  line-height: 1;
}
.nav a .nav-badge { margin-inline-start: auto; }
.nav-toggle .nav-badge { margin-inline-start: 4px; }

/* ---------- Collapsible activity sections ---------- */
.activity-section { border: 1px solid var(--line-soft); border-radius: var(--r-md); margin-bottom: var(--s3); overflow: hidden; background: var(--bg-soft); }
.activity-section summary {
  cursor: pointer;
  list-style: none;
  padding: 14px 16px;
  background: var(--panel-raised);
  font-weight: 800;
  font-size: 13.5px;
  color: var(--ink);
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: background .15s;
}
.activity-section summary:hover { background: var(--panel-hover); }
.activity-section summary::-webkit-details-marker { display: none; }
.activity-section summary .count-badge {
  background: var(--gold-soft);
  border: 1px solid var(--gold-dim);
  color: var(--gold);
  border-radius: var(--r-pill);
  padding: 2px 10px;
  font-size: 12px;
  font-family: var(--font-mono);
}
.activity-section summary::before { content: '▸'; margin-inline-end: var(--s2); color: var(--gold-dim); transition: transform .15s; display: inline-block; }
.activity-section[open] summary::before { transform: rotate(90deg); }
.activity-section .activity-body { padding: var(--s4); }

/* ---------- Holdings list ---------- */
.holdings-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--s2); }
.holdings-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s3);
  background: var(--panel-raised);
  border: 1px solid var(--line-soft);
  border-inline-start: 3px solid var(--gold-dim);
  border-radius: var(--r-sm);
  padding: 13px 16px;
  font-size: 14px;
  transition: border-color .15s, background .15s;
}
.holdings-list li:hover { border-inline-start-color: var(--gold); background: var(--panel-hover); }
.holdings-list li > span:first-child { color: var(--ink-dim); font-weight: 600; }
.holdings-list .qty { color: var(--gold); font-weight: 700; font-family: var(--font-mono); font-size: 15px; text-align: end; font-variant-numeric: tabular-nums; }

/* ---------- Stat grid (dashboard) ---------- */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--s3);
  margin-bottom: var(--s2);
}
.stat-card {
  background: var(--panel-raised);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-md);
  padding: var(--s4);
  min-width: 0;
  transition: border-color .15s;
}
.stat-card:hover { border-color: var(--line); }
.stat-card .stat-label { color: var(--ink-dim); font-size: 12px; margin-bottom: 6px; }
.stat-card .stat-value {
  color: var(--gold);
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 22px;
  letter-spacing: -0.5px;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.stat-card.stat-hero {
  border-color: var(--gold-dim);
  background: linear-gradient(135deg, rgba(210,172,90,0.12), var(--panel-raised) 65%);
  padding: var(--s5);
}
.stat-card.stat-hero .stat-label { color: var(--gold-dim); text-transform: uppercase; letter-spacing: 1.2px; font-size: 11px; font-weight: 800; }
.stat-card.stat-hero .stat-value { font-size: 30px; }

.quick-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--s2);
}
.quick-actions a {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
  text-decoration: none;
  background: var(--panel-raised);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: var(--s4);
  color: var(--ink);
  font-weight: 700;
  font-size: 13.5px;
  transition: border-color .15s, background .15s, transform .1s;
}
.quick-actions a:hover { border-color: var(--gold); background: var(--panel-hover); transform: translateY(-1px); }
.quick-actions a .qa-icon { font-size: 20px; }
.quick-actions a .qa-sub { color: var(--ink-faint); font-size: 11px; font-weight: 400; }

/* ---------- Icon picker ---------- */
.icon-picker { display: flex; flex-wrap: wrap; gap: var(--s2); margin-top: 6px; }
.icon-choice { position: relative; cursor: pointer; }
.icon-choice input { position: absolute; opacity: 0; width: 100%; height: 100%; cursor: pointer; margin: 0; }
.icon-choice span {
  display: flex; align-items: center; justify-content: center;
  width: 44px; height: 44px; font-size: 20px;
  border: 1px solid var(--line); border-radius: var(--r-sm);
  background: var(--panel-raised);
  transition: border-color .15s, background .15s;
}
.icon-choice:hover span { border-color: var(--gold-dim); }
.icon-choice input:checked + span { border-color: var(--gold); background: var(--gold-soft); }
.edit-row td { background: var(--bg-soft); }

/* ---------- Empty state ---------- */
.empty {
  color: var(--ink-faint);
  font-size: 13px;
  text-align: center;
  padding: var(--s8) var(--s4);
  border: 1px dashed var(--line);
  border-radius: var(--r-md);
  background: rgba(255,255,255,0.012);
}

.app-footer {
  text-align: center;
  color: var(--ink-faint);
  font-size: 11px;
  font-family: var(--font-mono);
  padding: var(--s6) 0 var(--s2);
  opacity: 0.65;
}

@media (prefers-reduced-motion: reduce) {
  * { animation-duration: .01ms !important; transition-duration: .01ms !important; scroll-behavior: auto !important; }
}

@media (min-width: 601px) and (max-width: 860px) {
  .wrap { padding: 0 var(--s4) 56px; }
  .stat-grid, .quick-actions { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 600px) {
  .wrap { padding: 0 var(--s3) 56px; }
  .ledger-bar {
    flex-direction: column; align-items: stretch; gap: var(--s2);
    margin: var(--s2) 0 var(--s4); padding: var(--s3); border-radius: var(--r-md);
  }
  .ledger-bar > .brand { justify-content: center; font-size: 16px; gap: 6px; }
  .ledger-bar > .brand .seal { width: 24px; height: 24px; }
  .ledger-bar > .id-lang-row { justify-content: center; }
  .ledger-bar > .id-lang-row .id-chip { text-align: center; flex: 1; }
  .ledger-bar > .lang-switch-wrapper { display: flex; justify-content: center; }
  .ledger-bar > .balance-chip { text-align: center; font-size: 15px; padding: 11px 14px; }
  .lang-switch { inset-inline-end: auto; left: 0; right: 0; min-width: 0; }
  .nav-wrapper { width: 100%; }
  .nav-toggle { width: 100%; padding: 10px 12px; font-size: 14px; }
  .nav {
    position: absolute;
    inset-inline-start: 0;
    inset-inline-end: 0;
    left: 0; right: 0;
    top: calc(100% + 8px);
    min-width: 0;
    max-height: 68vh;
    overflow-y: auto;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
  .nav a { justify-content: center; text-align: center; font-size: 12.5px; padding: 12px 8px; line-height: 1.35; }
  .nav a .nav-badge { margin-inline-start: 6px; }
  .nav a.nav-logout { grid-column: 1 / -1; margin-top: var(--s1); }
  .nav-section-label { grid-column: 1 / -1; }
  .stat-grid, .quick-actions { grid-template-columns: 1fr 1fr; gap: var(--s2); }
  .stat-card.stat-hero { grid-column: 1 / -1; }
  .stock-card { padding: var(--s3); }
  .id-chip { font-size: 12px; padding: 8px 12px; }
  .stat-card { padding: var(--s3); }
  .stat-card .stat-label { font-size: 11px; margin-bottom: 3px; }
  .stat-card .stat-value { font-size: 18px; }
  .stat-card.stat-hero { padding: var(--s4); }
  .stat-card.stat-hero .stat-value { font-size: 26px; }
  .quick-actions a { padding: var(--s3); gap: 2px; font-size: 12.5px; }
  .quick-actions a .qa-icon { font-size: 17px; }
  .quick-actions a .qa-sub { font-size: 10px; }
  .panel { padding: var(--s4); margin-bottom: var(--s4); border-radius: var(--r-md); }
  .panel h2 { font-size: 12px; margin-bottom: var(--s3); }
  .panel h3 { margin: var(--s4) 0 var(--s2); padding-top: var(--s4); }
  .dash-greeting h1 { font-size: 20px; }
  form { max-width: none; }
  table, thead, tbody, th, td, tr { display: block; }
  thead { display: none; }
  tr { border: 1px solid var(--line-soft); border-radius: var(--r-sm); margin-bottom: var(--s2); padding: var(--s2); background: var(--panel-raised); }
  tr:nth-child(even) td, tr:hover td { background: transparent; }
  td { border: none; display: flex; justify-content: space-between; gap: var(--s3); padding: 7px 8px; text-align: end; }
  td::before { content: attr(data-label); color: var(--ink-dim); font-family: var(--font-sans); font-size: 11px; text-align: start; flex-shrink: 0; }
  td[hidden], tr[hidden] { display: none !important; }
}

/* جدول "دايمًا مكدّس" - بيتحول لكروت label:value في كل الشاشات */
table.stacked-always, table.stacked-always thead, table.stacked-always tbody,
table.stacked-always th, table.stacked-always td, table.stacked-always tr { display: block; }
table.stacked-always thead { display: none; }
table.stacked-always tr {
  border: 1px solid var(--line-soft); border-radius: var(--r-md); margin-bottom: var(--s2);
  padding: var(--s3); background: var(--panel-raised);
}
table.stacked-always tr:hover td, table.stacked-always tr:nth-child(even) td { background: transparent; }
table.stacked-always td {
  border: none; display: flex; justify-content: space-between; align-items: flex-start;
  gap: var(--s4); padding: 7px 2px; text-align: end;
}
table.stacked-always td::before {
  content: attr(data-label); color: var(--ink-dim); font-family: var(--font-sans);
  font-size: 11px; flex-shrink: 0; text-align: start;
}
table.stacked-always td[hidden] { display: none !important; }


/* =========================================================
   GNID BANK — طبقة التحسين البصري (Cards & Surfaces v2)
   ترقية شكل الكروت والأسطح من غير أي تغيير في الـ HTML.
   ========================================================= */

:root {
  --r-sm: 10px; --r-md: 14px; --r-lg: 18px;
  --edge: rgba(255,255,255,0.055);
  --gold-line: rgba(210,172,90,0.34);
  --glow-gold: 0 0 0 1px rgba(210,172,90,0.16), 0 14px 34px -18px rgba(210,172,90,0.45);
  --card-grad: linear-gradient(168deg, rgba(255,255,255,0.045) 0%, rgba(255,255,255,0.012) 42%, rgba(0,0,0,0.10) 100%);
}

/* ---------- Panels ---------- */
.panel {
  position: relative;
  background:
    var(--card-grad),
    var(--panel);
  border: 1px solid var(--edge);
  border-radius: var(--r-lg);
  padding: var(--s6);
  box-shadow: 0 1px 0 rgba(255,255,255,0.04) inset, 0 10px 30px -22px rgba(0,0,0,0.9);
  overflow: hidden;
}
.panel::before {
  content: "";
  position: absolute; inset-inline: 0; top: 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--gold-line), transparent);
  opacity: .75;
  pointer-events: none;
}
.panel > * { position: relative; }

.panel h2 {
  display: flex; align-items: center; gap: var(--s2);
  font-size: 12px; letter-spacing: 1.8px;
}
.panel h2::before {
  content: ""; width: 3px; height: 15px; border-radius: 2px; flex: none;
  background: linear-gradient(180deg, var(--gold), var(--gold-dim));
  box-shadow: 0 0 10px rgba(210,172,90,0.45);
}

/* ---------- Stat cards ---------- */
.stat-grid { gap: var(--s3); }
.stat-card {
  position: relative;
  background: var(--card-grad), var(--panel-raised);
  border: 1px solid var(--edge);
  border-radius: var(--r-md);
  padding: var(--s5) var(--s4);
  box-shadow: 0 1px 0 rgba(255,255,255,0.035) inset, 0 8px 24px -20px #000;
  overflow: hidden;
  transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease;
}
.stat-card::after {
  content: "";
  position: absolute; inset-inline-start: 0; top: 12%; bottom: 12%;
  width: 2px; border-radius: 2px;
  background: linear-gradient(180deg, var(--gold-dim), transparent);
  opacity: .55;
}
.stat-card:hover {
  transform: translateY(-2px);
  border-color: var(--gold-line);
  box-shadow: var(--glow-gold);
}
.stat-card .stat-label {
  font-size: 11px; font-weight: 800; letter-spacing: .9px;
  text-transform: uppercase; color: var(--ink-dim); margin-bottom: 8px;
}
.stat-card .stat-value { letter-spacing: -0.6px; font-size: clamp(15px, 4.5vw, 22px); overflow-wrap: anywhere; }

.stat-card.stat-hero {
  background:
    radial-gradient(120% 160% at 100% 0%, rgba(210,172,90,0.20), transparent 55%),
    var(--card-grad),
    var(--panel-raised);
  border-color: var(--gold-line);
  box-shadow: var(--glow-gold);
}
.stat-card.stat-hero::after { width: 3px; background: linear-gradient(180deg, var(--gold), rgba(210,172,90,0)); opacity: .9; }
.stat-card.stat-hero .stat-value {
  background: linear-gradient(100deg, #F2DCA6, var(--gold) 55%, #B8933F);
  -webkit-background-clip: text; background-clip: text; color: transparent;
  font-size: clamp(18px, 6vw, 30px);
}

/* ---------- Quick actions ---------- */
.quick-actions { gap: var(--s3); }
.quick-actions a {
  position: relative;
  background: var(--card-grad), var(--panel-raised);
  border: 1px solid var(--edge);
  border-radius: var(--r-md);
  padding: var(--s4);
  box-shadow: 0 8px 24px -22px #000;
  overflow: hidden;
}
.quick-actions a .qa-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 38px; height: 38px; margin-bottom: 6px;
  border-radius: 11px;
  background: linear-gradient(160deg, rgba(210,172,90,0.20), rgba(210,172,90,0.05));
  border: 1px solid var(--gold-line);
  font-size: 18px;
}
.quick-actions a:hover {
  transform: translateY(-2px);
  border-color: var(--gold-line);
  box-shadow: var(--glow-gold);
  background: var(--card-grad), var(--panel-hover);
}

/* ---------- Nav menu cards ---------- */
.nav { border-radius: var(--r-lg); border-color: var(--edge); }
.nav a {
  background: var(--card-grad), var(--panel-raised);
  border-color: var(--edge);
  border-radius: 12px;
}
.nav a:hover, .nav a:focus-visible {
  border-color: var(--gold-line);
  box-shadow: var(--glow-gold);
}

/* ---------- Header ---------- */
.ledger-bar {
  border-radius: var(--r-lg);
  border-color: var(--edge);
  background: linear-gradient(180deg, color-mix(in srgb, var(--panel) 92%, transparent), color-mix(in srgb, var(--bg-soft) 88%, transparent));
  box-shadow: 0 10px 30px -26px #000;
}
.balance-chip {
  border-color: var(--gold-line);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
}
.id-chip, .lang-toggle, .notif-bell {
  background: var(--card-grad), var(--panel-raised);
  border-color: var(--edge);
  border-radius: 11px;
}

/* ---------- Holdings / list cards ---------- */
.holdings-list li {
  background: var(--card-grad), var(--panel-raised);
  border: 1px solid var(--edge);
  border-inline-start: 3px solid var(--gold-dim);
  border-radius: var(--r-md);
  padding: 14px 16px;
}
.holdings-list li:hover { border-color: var(--gold-line); border-inline-start-color: var(--gold); box-shadow: var(--glow-gold); }

/* ---------- Activity / details cards ---------- */
.activity-section {
  border-radius: var(--r-md);
  border-color: var(--edge);
  background: var(--bg-soft);
  box-shadow: 0 8px 24px -24px #000;
}
.activity-section summary { background: var(--card-grad), var(--panel-raised); }

/* ---------- Buttons ---------- */
button, .btn { border-radius: 12px; }
button:not(.secondary):not(.danger):not(.buy):not(.sell):not(.status-pill):not(.lang-toggle):not(.nav-toggle):not(.flash-close):not(.user-toggle) {
  background: linear-gradient(180deg, #E4C275, var(--gold) 45%, #B8933F);
  box-shadow: 0 8px 20px -12px rgba(210,172,90,0.7), inset 0 1px 0 rgba(255,255,255,0.35);
}
button.secondary { background: var(--card-grad), var(--panel-raised); border-color: var(--edge); }

/* ---------- Inputs ---------- */
input, select, textarea {
  border-radius: 12px;
  background: color-mix(in srgb, var(--bg-soft) 88%, #000);
  border-color: var(--edge);
}

/* ---------- Tables as cards ---------- */
table.stacked-always tr, .card { border-radius: var(--r-md); border-color: var(--edge); }

/* ---------- Empty state ---------- */
.empty { border-radius: var(--r-md); border-color: var(--edge); }

/* ---------- Profile nudge ---------- */
.profile-nudge { border-radius: var(--r-lg); border-color: var(--gold-line); box-shadow: var(--glow-gold); }

@media (max-width: 600px) {
  .stat-card { padding: var(--s4) var(--s3); }
  .quick-actions a .qa-icon { width: 32px; height: 32px; font-size: 16px; }
  tr { border-radius: var(--r-md); border-color: var(--edge); background: var(--card-grad), var(--panel-raised); }
}
</style>
</head>
<body>
<div class="wrap">
  <div class="ledger-bar">
    <div class="brand"><img class="seal" src="{{ LOGO_DATA_URI }}" alt="GNID"> {{ tr('brand') }}</div>
    {% if current_user.is_authenticated %}
    <div class="id-lang-row">
      <a href="{{ url_for('notifications') }}" class="notif-bell" aria-label="notifications">🔔{% if unread_notifications_count() %}<span class="notif-badge">{{ unread_notifications_count() }}</span>{% endif %}</a>
      <div class="id-chip">{{ tr('your_id_label') }}: <b>#{{ current_user.account_id }}</b></div>
      <div class="lang-switch-wrapper">
        <button type="button" class="lang-toggle" id="langToggle">{{ LANGUAGES.get(session.get('lang', 'ar')) }}</button>
        <div class="lang-switch" id="langSwitch">
          {% for code, label in LANGUAGES.items() %}
            <a href="{{ url_for('set_lang', code=code) }}" class="{{ 'active' if session.get('lang','ar') == code }}">{{ label }}</a>
          {% endfor %}
        </div>
      </div>
    </div>
    {% else %}
    <div class="lang-switch-wrapper">
      <button type="button" class="lang-toggle" id="langToggle">{{ LANGUAGES.get(session.get('lang', 'ar')) }}</button>
      <div class="lang-switch" id="langSwitch">
        {% for code, label in LANGUAGES.items() %}
          <a href="{{ url_for('set_lang', code=code) }}" class="{{ 'active' if session.get('lang','ar') == code }}">{{ label }}</a>
        {% endfor %}
      </div>
    </div>
    {% endif %}

    {% if current_user.is_authenticated %}
    <div class="nav-wrapper">
      {% if current_user.is_admin or current_user.is_mod %}
      {% set total_pending = pending_loans_count() + pending_withdrawals_count() + pending_company_requests_count() %}
      {% endif %}
      <button type="button" class="nav-toggle" id="navToggle">☰ {{ tr('menu_label') }}{% if total_pending %}<span class="nav-badge">{{ total_pending }}</span>{% endif %}</button>
      <div class="nav-backdrop" id="navBackdrop"></div>
      <nav class="nav" id="mainNav">
        <a href="{{ url_for('dashboard') }}">👤 {{ tr('my_account') }}</a>
        <a href="{{ url_for('deposit') }}">💰 {{ tr('add_balance') }}</a>
        <a href="{{ url_for('market') }}">📈 {{ tr('market') }}</a>
        <a href="{{ url_for('invest') }}">🏦 {{ tr('investment') }}</a>
        <a href="{{ url_for('withdraw') }}">💸 {{ tr('withdraw') }}</a>
        <a href="{{ url_for('debts') }}">🤝 {{ tr('debts') }}</a>
        {% if not (current_user.is_admin or current_user.is_mod) and COMPANY_FEATURE_ENABLED %}
        <a href="{{ url_for('company_apply') }}">🏭 {{ tr('company_apply_nav') }}</a>
        {% endif %}
        <a href="{{ url_for('currency_apply') }}">🪙 {{ tr('nav_currency_apply') }}</a>
        <a href="{{ url_for('settings') }}">🔧 {{ tr('settings') }}</a>
        <a href="{{ url_for('guide') }}">📘 {{ tr('guide_nav') }}</a>
        {% if current_user.is_admin %}
        <div class="nav-section-label">⚙️ {{ tr('admin_section_label') }}</div>
        <a href="{{ url_for('admin_stocks') }}" class="nav-admin">📊 {{ tr('manage_stocks') }}</a>
        {% if COMPANY_FEATURE_ENABLED %}<a href="{{ url_for('admin_companies') }}" class="nav-admin">🏭 {{ tr('admin_companies_nav') }}{% if pending_company_requests_count() %}<span class="nav-badge">{{ pending_company_requests_count() }}</span>{% endif %}</a>{% endif %}
        <a href="{{ url_for('admin_currencies') }}" class="nav-admin">🪙 {{ tr('nav_admin_currencies') }}{% if pending_currency_requests_count() %}<span class="nav-badge">{{ pending_currency_requests_count() }}</span>{% endif %}</a>
        <a href="{{ url_for('admin_dividends') }}" class="nav-admin">💰 {{ tr('admin_dividends_nav') }}</a>
        <a href="{{ url_for('admin_notifications') }}" class="nav-admin">🔔 {{ tr('admin_notifications_nav') }}</a>
        <a href="{{ url_for('admin_users') }}" class="nav-admin">👥 {{ tr('manage_users_title') }}</a>
        <a href="{{ url_for('admin_investments') }}" class="nav-admin">🏦 {{ tr('nav_manage_investments') }}</a>
        <a href="{{ url_for('admin_withdrawals') }}" class="nav-admin">💸 {{ tr('nav_manage_withdrawals') }}{% if pending_withdrawals_count() %}<span class="nav-badge">{{ pending_withdrawals_count() }}</span>{% endif %}</a>
        <a href="{{ url_for('admin_loans') }}" class="nav-admin">🤝 {{ tr('nav_manage_loans') }}{% if pending_loans_count() %}<span class="nav-badge">{{ pending_loans_count() }}</span>{% endif %}</a>
        <a href="{{ url_for('admin_deposits') }}" class="nav-admin">🔑 {{ tr('deposits_and_transfers') }}</a>
        <a href="{{ url_for('admin_activity') }}" class="nav-admin">📜 {{ tr('full_activity_log') }}</a>
        <a href="{{ url_for('admin_treasury') }}" class="nav-admin">🏛️ {{ tr('treasury_nav') }}</a>
        <a href="{{ url_for('admin_vault_history') }}" class="nav-admin">📜 {{ tr('vault_history_title') }}</a>
        {% elif current_user.is_mod %}
        <div class="nav-section-label">👁️ {{ tr('admin_section_label') }}</div>
        {% if COMPANY_FEATURE_ENABLED %}<a href="{{ url_for('admin_companies') }}" class="nav-admin">🏭 {{ tr('admin_companies_nav') }}{% if pending_company_requests_count() %}<span class="nav-badge">{{ pending_company_requests_count() }}</span>{% endif %}</a>{% endif %}
        <a href="{{ url_for('admin_currencies') }}" class="nav-admin">🪙 {{ tr('nav_admin_currencies') }}{% if pending_currency_requests_count() %}<span class="nav-badge">{{ pending_currency_requests_count() }}</span>{% endif %}</a>
        <a href="{{ url_for('admin_dividends') }}" class="nav-admin">💰 {{ tr('admin_dividends_nav') }}</a>
        <a href="{{ url_for('admin_notifications') }}" class="nav-admin">🔔 {{ tr('admin_notifications_nav') }}</a>
        <a href="{{ url_for('admin_users') }}" class="nav-admin">👥 {{ tr('manage_users_title') }}</a>
        <a href="{{ url_for('admin_investments') }}" class="nav-admin">🏦 {{ tr('nav_manage_investments') }}</a>
        <a href="{{ url_for('admin_withdrawals') }}" class="nav-admin">💸 {{ tr('nav_manage_withdrawals') }}{% if pending_withdrawals_count() %}<span class="nav-badge">{{ pending_withdrawals_count() }}</span>{% endif %}</a>
        <a href="{{ url_for('admin_loans') }}" class="nav-admin">🤝 {{ tr('nav_manage_loans') }}{% if pending_loans_count() %}<span class="nav-badge">{{ pending_loans_count() }}</span>{% endif %}</a>
        <a href="{{ url_for('admin_deposits') }}" class="nav-admin">🔑 {{ tr('deposits_and_transfers') }}</a>
        <a href="{{ url_for('admin_activity') }}" class="nav-admin">📜 {{ tr('full_activity_log') }}</a>
        <a href="{{ url_for('admin_treasury') }}" class="nav-admin">🏛️ {{ tr('treasury_nav') }}</a>
        <a href="{{ url_for('admin_vault_history') }}" class="nav-admin">📜 {{ tr('vault_history_title') }}</a>
        {% endif %}
        <a href="{{ url_for('logout') }}" class="nav-logout">🚪 {{ tr('logout') }}</a>
      </nav>
    </div>
    {% if request.endpoint != 'dashboard' %}<div class="balance-chip">{{ current_user.balance|money }} {{ tr('balance_word') }}</div>{% endif %}
    {% endif %}
  </div>

  {% with messages = get_flashed_messages() %}
    {% if messages %}<ul class="flash-stack" id="flashStack">{% for m in messages %}<li>{{ m }}<button type="button" class="flash-close" aria-label="close" onclick="this.parentElement.remove()">×</button></li>{% endfor %}</ul>{% endif %}
  {% endwith %}

  {{ content|safe }}

  <div class="app-footer">GNID BANK · v{{ APP_VERSION }}</div>
</div>
<script>
(function () {
  var toggle = document.getElementById('navToggle');
  var nav = document.getElementById('mainNav');
  var backdrop = document.getElementById('navBackdrop');
  if (!toggle || !nav) return;
  function setOpen(isOpen) {
    nav.classList.toggle('open', isOpen);
    if (backdrop) backdrop.classList.toggle('open', isOpen);
  }
  toggle.addEventListener('click', function (e) {
    e.stopPropagation();
    setOpen(!nav.classList.contains('open'));
  });
  nav.addEventListener('click', function (e) { e.stopPropagation(); });
  if (backdrop) backdrop.addEventListener('click', function () { setOpen(false); });
  document.addEventListener('click', function () { setOpen(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
})();

(function () {
  var stack = document.getElementById('flashStack');
  if (!stack) return;
  Array.prototype.forEach.call(stack.querySelectorAll('li'), function (li) {
    setTimeout(function () {
      li.classList.add('flash-hide');
      setTimeout(function () { if (li.parentNode) li.remove(); }, 260);
    }, 5000);
  });
})();

(function () {
  var toggle = document.getElementById('langToggle');
  var menu = document.getElementById('langSwitch');
  if (!toggle || !menu) return;
  function setOpen(isOpen) { menu.classList.toggle('open', isOpen); }
  toggle.addEventListener('click', function (e) {
    e.stopPropagation();
    setOpen(!menu.classList.contains('open'));
  });
  menu.addEventListener('click', function (e) { e.stopPropagation(); });
  document.addEventListener('click', function () { setOpen(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
})();

(function () {
  function formatMoneyStr(raw) {
    raw = raw.replace(/[^0-9.]/g, '');
    var firstDot = raw.indexOf('.');
    if (firstDot !== -1) {
      raw = raw.slice(0, firstDot + 1) + raw.slice(firstDot + 1).replace(/\\./g, '');
    }
    var parts = raw.split('.');
    var intPart = parts[0].replace(/^0+(?=\\d)/, '');
    var formatted = intPart ? Number(intPart).toLocaleString('en-US') : '';
    return parts.length > 1 ? formatted + '.' + parts[1] : formatted;
  }
  var inputs = document.querySelectorAll('input.money-input');
  inputs.forEach(function (input) {
    if (input.value) input.value = formatMoneyStr(input.value);
    input.addEventListener('input', function () {
      var pos = input.selectionStart;
      var lenBefore = input.value.length;
      input.value = formatMoneyStr(input.value);
      var lenAfter = input.value.length;
      var newPos = Math.max(0, pos + (lenAfter - lenBefore));
      input.setSelectionRange(newPos, newPos);
    });
  });
  document.querySelectorAll('form').forEach(function (form) {
    form.addEventListener('submit', function () {
      form.querySelectorAll('input.money-input').forEach(function (input) {
        input.value = input.value.replace(/,/g, '');
      });
    });
  });
})();

(function () {
  // بدل ما نحط نص الترجمة جوه onsubmit="return confirm('...')" (بينكسر لو النص فيه علامة اقتباس زي "it's")،
  // بنقرا النص من data-confirm بشكل آمن مهما كان فيه علامات اقتباس أو أي لغة.
  document.querySelectorAll('form.confirm-form').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      var msg = form.getAttribute('data-confirm') || '';
      if (!window.confirm(msg)) {
        e.preventDefault();
      }
    });
  });
})();

(function () {
  // حماية CSRF: بنحط توكن الجلسة كحقل مخفي في كل فورم POST في الصفحة تلقائيًا،
  // من غير ما نحتاج نعدّل كل فورم لوحده في كل صفحة.
  var meta = document.querySelector('meta[name="csrf-token"]');
  var token = meta ? meta.getAttribute('content') : '';
  if (!token) return;
  document.querySelectorAll('form').forEach(function (form) {
    if ((form.method || 'get').toLowerCase() !== 'post') return;
    if (form.querySelector('input[name="csrf_token"]')) return;
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'csrf_token';
    input.value = token;
    form.appendChild(input);
  });
})();
</script>
</body>
</html>
"""


def page(content_html, **ctx):
    body = render_template_string(content_html, **ctx)
    return render_template_string(BASE, content=body)


REGISTER_HTML = """
<div class="auth-shell">
  <div class="auth-hero">
    <img class="auth-seal" src="{{ LOGO_DATA_URI }}" alt="GNID">
    <div class="auth-title">{{ tr('brand') }}</div>
    <div class="auth-rule"></div>
    <p class="auth-tagline">{{ tr('auth_tagline') }}</p>
  </div>

  <div class="auth-card">
    <nav class="auth-tabs">
      <a href="{{ url_for('login') }}">{{ tr('login_title') }}</a>
      <a class="active" href="{{ url_for('register') }}">{{ tr('register_title') }}</a>
    </nav>
    <h2>{{ tr('register_title') }}</h2>
    <p class="lede">{{ tr('register_lede') }}</p>
    <form method="post">
      <div><label>{{ tr('username') }}</label><input name="username" autocomplete="username" required></div>
      <div><label>{{ tr('telegram_user') }}</label><input name="telegram_username" placeholder="@username" pattern="^@?[A-Za-z][A-Za-z0-9_]{4,31}$" title="{{ tr('flash_telegram_invalid_format') }}" required></div>
      <div class="pw-field"><label>{{ tr('password') }}</label><input name="password" type="password" autocomplete="new-password" required><button class="pw-toggle" type="button" data-pw-toggle aria-label="show/hide">&#128065;</button></div>
      <div class="pw-field"><label>{{ tr('confirm_password_label') }}</label><input name="confirm_password" type="password" autocomplete="new-password" required><button class="pw-toggle" type="button" data-pw-toggle aria-label="show/hide">&#128065;</button></div>
      <button type="submit">{{ tr('register_btn') }}</button>
    </form>
    <p class="auth-link" style="margin-top:16px; text-align:center;">{{ tr('have_account') }} <a href="{{ url_for('login') }}">{{ tr('login_link') }}</a></p>
  </div>

  <p class="auth-note">&#128274; GNID BANK</p>
</div>

<div class="auth-footer-links">
  <a href="https://t.me/GNIDBANK" target="_blank" rel="noopener">📱 {{ tr('telegram_group_link') }}</a>
  <a href="https://diplomacia.com.tr/" target="_blank" rel="noopener">🎮 {{ tr('play_game_link') }}</a>
</div>

<script>
document.querySelectorAll('[data-pw-toggle]').forEach(function(b){
  b.addEventListener('click', function(){
    var i = b.parentElement.querySelector('input');
    if (!i) return;
    i.type = i.type === 'password' ? 'text' : 'password';
    b.style.color = i.type === 'text' ? 'var(--gold)' : '';
  });
});
</script>
"""

LOGIN_HTML = """
<div class="auth-shell">
  <div class="auth-hero">
    <img class="auth-seal" src="{{ LOGO_DATA_URI }}" alt="GNID">
    <div class="auth-title">{{ tr('brand') }}</div>
    <div class="auth-rule"></div>
    <p class="auth-tagline">{{ tr('auth_tagline') }}</p>
  </div>

  <div class="auth-card">
    <nav class="auth-tabs">
      <a class="active" href="{{ url_for('login') }}">{{ tr('login_title') }}</a>
      <a href="{{ url_for('register') }}">{{ tr('register_title') }}</a>
    </nav>
    <h2>{{ tr('login_title') }}</h2>
    <p class="lede">{{ tr('login_lede') }}</p>
    <form method="post">
      <div><label>{{ tr('username') }}</label><input name="username" autocomplete="username" required></div>
      <div class="pw-field"><label>{{ tr('password') }}</label><input name="password" type="password" autocomplete="current-password" required><button class="pw-toggle" type="button" data-pw-toggle aria-label="show/hide">&#128065;</button></div>
      <button type="submit">{{ tr('login_btn') }}</button>
    </form>
    <p class="auth-link" style="margin-top:16px; text-align:center;">{{ tr('no_account') }} <a href="{{ url_for('register') }}">{{ tr('register_link') }}</a></p>
  </div>

  <p class="auth-note">&#128274; GNID BANK</p>
</div>

<div class="auth-footer-links">
  <a href="https://t.me/GNIDBANK" target="_blank" rel="noopener">📱 {{ tr('telegram_group_link') }}</a>
  <a href="https://diplomacia.com.tr/" target="_blank" rel="noopener">🎮 {{ tr('play_game_link') }}</a>
</div>

<script>
document.querySelectorAll('[data-pw-toggle]').forEach(function(b){
  b.addEventListener('click', function(){
    var i = b.parentElement.querySelector('input');
    if (!i) return;
    i.type = i.type === 'password' ? 'text' : 'password';
    b.style.color = i.type === 'text' ? 'var(--gold)' : '';
  });
});
</script>
"""

DASHBOARD_HTML = """
<div class="dash-greeting">
  <h1>{{ tr('greeting_hello') }}, {{ current_user.username }} 👋</h1>
  <p>{{ greeting_date }}</p>
</div>

{% if not current_user.telegram_verified and not (current_user.is_admin or current_user.is_mod) %}
<a href="{{ url_for('settings') }}#verify-panel" class="profile-nudge">
  <span class="profile-nudge-icon">🔔</span>
  <span class="profile-nudge-text">
    <b>{{ tr('complete_profile_title') }}</b>
    <span>{{ tr('complete_profile_body') }}</span>
  </span>
  <span class="profile-nudge-arrow">›</span>
</a>
{% endif %}

{% if current_user.is_frozen %}
<div class="panel" style="border-color:var(--red); background:rgba(180,83,68,0.10);">
  <h2 style="color:var(--red-ink);">{{ tr('account_frozen_banner_title') }}</h2>
  <p class="lede" style="color:var(--ink);">{{ tr('account_frozen_banner_body') }}</p>
  <a href="{{ url_for('debts') }}" style="color:var(--gold); font-weight:700;">{{ tr('section_loans') }} ›</a>
</div>
{% elif loan_due_soon %}
<div class="panel" style="border-color:var(--gold);">
  <h2 style="color:var(--gold);">{{ tr('loan_due_soon_title') }}</h2>
  <p class="lede" style="color:var(--ink);">{{ tr('loan_due_soon_banner_body').format(amount=(loan_due_soon.repay_amount or loan_due_soon.amount)|money, due_date=loan_due_soon.due_date.strftime("%Y-%m-%d")) }}</p>
  <a href="{{ url_for('debts') }}" style="color:var(--gold); font-weight:700;">{{ tr('section_loans') }} ›</a>
</div>
{% endif %}

<div class="panel">
  <h2>{{ tr('account_summary') }}</h2>
  <p class="lede">{{ tr('your_account_id') }}: <span style="color:var(--gold); font-family:'IBM Plex Mono',monospace; font-weight:700;">#{{ current_user.account_id }}</span>
    · {{ tr('telegram_label') }}: {{ current_user.telegram_username|tglink(current_user.telegram_has_username, current_user.telegram_chat_id)|safe }}
    {% if current_user.telegram_verified %}<span class="status-pill ok" style="margin-inline-start:6px;">{{ tr('telegram_verify_status_verified') }}</span>{% endif %}</p>

  <div class="stat-grid" style="margin-top:16px;">
    <div class="stat-card stat-hero">
      <div class="stat-label">{{ tr('balance_word') }}</div>
      <div class="stat-value">{{ current_user.balance|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('stat_active_investments') }}</div>
      <div class="stat-value">{{ active_investments_count }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('stat_total_invested') }}</div>
      <div class="stat-value">{{ total_invested|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('stat_expected_payout') }}</div>
      <div class="stat-value">{{ total_expected_payout|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('stat_holdings_count') }}</div>
      <div class="stat-value">{{ holdings|length }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('stat_holdings_value') }}</div>
      <div class="stat-value">{{ holdings_value|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('stat_pending_withdrawals') }}</div>
      <div class="stat-value">{{ pending_withdrawals_total|money if pending_withdrawals_total else tr('no_pending_withdrawals_dash') }}</div>
    </div>
  </div>
  {% if next_maturity %}
  <p class="lede" style="margin-top:4px;">{{ tr('next_maturity_label') }}: <b style="color:var(--gold);">{{ next_maturity.strftime("%Y-%m-%d %H:%M") }}</b> —
    <a href="{{ url_for('invest') }}" style="color:var(--gold);">{{ tr('view_investments_link') }} →</a></p>
  {% endif %}
</div>

<div class="panel">
  <h2>{{ tr('quick_actions_title') }}</h2>
  <div class="quick-actions">
    <a href="{{ url_for('deposit') }}"><span class="qa-icon">💰</span>{{ tr('qa_add_balance') }}<span class="qa-sub">{{ tr('deposit_title') }}</span></a>
    <a href="{{ url_for('market') }}"><span class="qa-icon">📈</span>{{ tr('qa_market') }}<span class="qa-sub">{{ tr('market') }}</span></a>
    <a href="{{ url_for('invest') }}"><span class="qa-icon">🏦</span>{{ tr('qa_invest') }}<span class="qa-sub">{% for days, pct in investment_terms.items() %}+{{ pct }}%/{{ days }}{{ tr('days_word') }}{{ ", " if not loop.last }}{% endfor %}</span></a>
    <a href="{{ url_for('withdraw') }}"><span class="qa-icon">💸</span>{{ tr('qa_withdraw') }}<span class="qa-sub">{{ tr('withdraw') }}</span></a>
    <a href="{{ url_for('debts') }}"><span class="qa-icon">🤝</span>{{ tr('qa_loans') }}<span class="qa-sub">{{ tr('debts') }}</span></a>
    <a href="{{ url_for('settings') }}"><span class="qa-icon">🔧</span>{{ tr('qa_settings') }}<span class="qa-sub">{{ tr('settings') }}</span></a>
    <a href="{{ url_for('guide') }}"><span class="qa-icon">📘</span>{{ tr('qa_guide') }}<span class="qa-sub">{{ tr('guide_nav') }}</span></a>
  </div>
</div>

<div class="panel">
  <h3>{{ tr('my_stocks') }}</h3>
  {% if holdings %}
  <ul class="holdings-list">
    {% for h in holdings %}<li><span>{{ h.stock.symbol }} {{ h.stock.name }}</span><span class="qty">{{ h.quantity|money }} <span style="color:var(--ink-dim); font-weight:400; font-size:12px;">≈ {{ (h.quantity * h.stock.price_stats().current)|money }}</span></span></li>{% endfor %}
  </ul>
  {% else %}
  <div class="empty">{{ tr('no_stocks_yet') }} <a href="{{ url_for('market') }}" style="color:var(--gold);">{{ tr('market_word') }}</a> {{ tr('start_here') }}</div>
  {% endif %}
</div>
"""

DEPOSIT_HTML = """
<div class="panel" style="max-width:560px;">
  <h2>{{ tr('deposit_title') }}</h2>
  <p class="lede">{{ tr('deposit_lede') }}</p>

  {% if not vault or not vault.token or not vault.healthy %}
  <div class="empty" style="border-color:var(--red); color:var(--red); margin-bottom:16px;">
    <b>{{ tr('transfers_paused_title') }}</b><br>
    <span style="font-size:12px;">{{ tr('transfers_paused_body') }}</span>
  </div>
  {% endif %}

  <h3>{{ tr('deposit_step2_title') }}</h3>
  <p class="lede">
    {{ tr('deposit_step2_body') }}
    <b style="color:var(--gold);">N + {{ current_user.account_id }}</b>
    — N {{ tr('balance_word') }}.
  </p>

  <div class="panel" style="background:var(--panel-raised); border-color:var(--gold-dim); margin:14px 0; padding:16px;">
    <div style="color:var(--gold-dim); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:1px; margin-bottom:10px;">
      {{ tr('deposit_worked_example_title') }}
    </div>
    <ul class="holdings-list">
      <li><span>{{ tr('desired_amount_label') }}</span><span class="qty">5,000</span></li>
      <li><span>{{ tr('your_id_is_label') }}</span><span class="qty">#{{ current_user.account_id }}</span></li>
      <li style="border-color:var(--gold-dim);"><span>{{ tr('amount_to_send_label') }}</span><span class="qty" style="font-size:18px;">{{ (5000 + (current_user.account_id|int))|money }}</span></li>
    </ul>
  </div>

  <p class="lede">
    {{ tr('deposit_example') }}
    <b style="color:var(--gold); font-family:'IBM Plex Mono',monospace;">{{ (5000 + (current_user.account_id|int))|money }}</b>
  </p>

  <h3>{{ tr('deposit_step1_title') }}</h3>
  <p class="lede">{{ tr('deposit_step1_body') }}</p>
  {% if vault and vault.account_name %}
  <ul class="holdings-list" style="margin-bottom:8px;">
    <li><span>{{ tr('vault_account_name') }}</span><span class="qty">{{ vault.account_name }}</span></li>
  </ul>
  {% if vault.account_url %}
  <a href="{{ vault.account_url }}" target="_blank" rel="noopener" class="btn" style="display:inline-block; text-decoration:none; margin-bottom:8px;">{{ tr('vault_account_link') }}</a>
  {% endif %}
  {% else %}
  <div class="empty">{{ tr('vault_account_not_set') }}</div>
  {% endif %}

  <h3>{{ tr('deposit_step3_title') }}</h3>
  <p class="lede">{{ tr('deposit_step3_body') }}</p>
</div>

<div class="panel">
  <h2>{{ tr('deposit_history') }}</h2>
  {% if deposits %}
  <table>
    <thead><tr><th>{{ tr('date_col') }}</th><th>{{ tr('credited_col') }}</th></tr></thead>
    <tbody>
    {% for d in deposits %}
      <tr>
        <td data-label="{{ tr('date_col') }}">{{ d.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="{{ tr('credited_col') }}">{{ d.amount_credited|money }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_deposits_yet') }}</div>{% endif %}
</div>
"""

MARKET_HTML = """
<div class="panel">
  <h2>{{ tr('market_index_title') }}</h2>
  <p class="lede">{{ tr('market_index_lede') }}</p>
  {% if index_labels|length > 1 %}
  {% if index_summary %}
  <div class="stat-grid" style="margin-bottom:14px;">
    <div class="stat-card stat-hero">
      <div class="stat-label">{{ tr('market_cap_label') }}</div>
      <div class="stat-value">{{ index_summary.current|money }}</div>
      <div style="color: {{ 'var(--green-ink)' if index_summary.change >= 0 else 'var(--red)' }}; font-size:13px; font-weight:700; margin-top:4px;">
        {{ '+' if index_summary.change >= 0 else '' }}{{ index_summary.change|money }} ({{ '+' if index_summary.pct >= 0 else '' }}{{ "%.2f"|format(index_summary.pct) }}%)
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('volume_label') }}</div>
      <div class="stat-value">{{ index_summary.total_volume|money }}</div>
    </div>
  </div>
  {% endif %}
  <p style="font-size:12px; color:var(--ink-dim); margin-bottom:4px;">{{ tr('market_cap_label') }}</p>
  <canvas id="marketPriceChart" height="110"></canvas>
  <p style="font-size:12px; color:var(--ink-dim); margin:14px 0 4px;">{{ tr('volume_label') }}</p>
  <canvas id="marketVolumeChart" height="60"></canvas>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
  <script>
  (function () {
    var labels = {{ index_labels|tojson }};
    var values = {{ index_values|tojson }};
    var volumes = {{ index_volumes|tojson }};
    var minVal = Math.min.apply(null, values);
    var maxVal = Math.max.apply(null, values);
    var range = maxVal - minVal;
    // لو التغير صغير جدًا، بنضيف هامش مبالغ فيه شوية حوالين القيم عشان الرسم
    // ما يبانش خط مسطح شبه ثابت - يعني نكبّر أي تذبذب حقيقي ونخليه واضح للعين
    var padding = range > 0 ? range * 0.35 : Math.max(maxVal * 0.02, 1);

    var xTicks = { color: '#93A1B4', maxRotation: 40, minRotation: 0, autoSkip: true, maxTicksLimit: 8 };

    new Chart(document.getElementById('marketPriceChart').getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: '{{ tr("market_cap_label") }}',
          data: values,
          borderColor: '#D2AC5A',
          backgroundColor: 'rgba(201,162,75,0.15)',
          borderWidth: 2.5,
          fill: true,
          tension: 0.25,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#D2AC5A',
        }]
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (item) { return '{{ tr("market_cap_label") }}: ' + Number(item.raw).toLocaleString(); } } }
        },
        scales: {
          x: { ticks: xTicks, grid: { display: false } },
          y: {
            suggestedMin: Math.max(0, minVal - padding),
            suggestedMax: maxVal + padding,
            ticks: { color: '#93A1B4', callback: function (v) { return Number(v).toLocaleString(); } },
            grid: { color: 'rgba(255,255,255,0.06)' }
          }
        }
      }
    });

    new Chart(document.getElementById('marketVolumeChart').getContext('2d'), {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: '{{ tr("volume_label") }}',
          data: volumes,
          backgroundColor: 'rgba(120,150,255,0.55)',
          barPercentage: 0.7,
        }]
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (item) { return '{{ tr("volume_label") }}: ' + Number(item.raw).toLocaleString(); } } }
        },
        scales: {
          x: { ticks: xTicks, grid: { display: false } },
          y: {
            beginAtZero: true,
            ticks: { color: '#93A1B4', callback: function (v) { return Number(v).toLocaleString(); } },
            grid: { color: 'rgba(255,255,255,0.06)' }
          }
        }
      }
    });
  })();
  </script>
  {% else %}
  <div class="empty">{{ tr('no_trades_yet') }}</div>
  {% endif %}
</div>

<div class="panel">
  <h2>{{ tr('ipo_title') }}</h2>
  <p class="lede">{{ tr('ipo_lede') }}</p>

  {% if ipo_stocks %}
  <div class="stock-card-grid">
    {% for s in ipo_stocks %}
      {% set stats = s.price_stats() %}
      <div class="stock-card" onclick="if (!event.target.closest('.stock-card-buy-form')) { window.location.href='{{ url_for('company_profile', stock_id=s.id) }}'; }" style="cursor:pointer;">
        <div class="stock-card-head">
          <span class="stock-card-icon">{{ s.symbol }}</span>
          <span class="stock-card-name">{{ s.name }}</span>
        </div>
        <div class="stock-card-price">{{ stats.current|money }}</div>
        <div class="stock-card-change {{ 'side-buy' if stats.change >= 0 else 'side-sell' }}">
          {{ '+' if stats.change >= 0 else '' }}{{ stats.change|money }} ({{ '+' if stats.pct >= 0 else '' }}{{ "%.2f"|format(stats.pct) }}%)
        </div>
        <div class="stock-card-meta">
          <div class="stock-card-meta-item">
            <span class="stock-card-meta-label">{{ tr('available') }}</span>
            <span class="stock-card-meta-value">{{ s.admin_supply|money }}</span>
          </div>
          <div class="stock-card-meta-item">
            <span class="stock-card-meta-label">{{ tr('market_cap_label') }}</span>
            <span class="stock-card-meta-value">{{ s.market_cap()|money }}</span>
          </div>
          <div class="stock-card-meta-item">
            <span class="stock-card-meta-label">{{ tr('owned_col') }}</span>
            <span class="stock-card-meta-value">{{ my_holdings.get(s.id, 0)|money }}</span>
          </div>
        </div>
        <form method="post" action="{{ url_for('buy_from_admin', stock_id=s.id) }}" class="stock-card-buy-form" onclick="event.stopPropagation();">
          <input name="quantity" type="number" min="1" required placeholder="{{ tr('quantity') }}">
          <button type="submit" class="buy">{{ tr('buy') }}</button>
        </form>
      </div>
    {% endfor %}
  </div>
  {% else %}<div class="empty">{{ tr('no_stocks_offered') }}</div>{% endif %}
</div>

<div class="panel">
  <h2>🪙 {{ tr('currencies_section_title') }}</h2>
  <p class="lede">{{ tr('trading_lede') }}</p>
  {% if currencies %}
  <div class="stock-card-grid">
    {% for s in currencies %}
      {% set stats = s.price_stats() %}
      <div class="stock-card" onclick="window.location.href='{{ url_for('company_profile', stock_id=s.id) }}';" style="cursor:pointer;">
        <div class="stock-card-head">
          <span class="stock-card-icon">{{ s.symbol }}</span>
          <span class="stock-card-name">{{ s.name }}{% if s.suspended %} · {{ tr('suspended_badge') }}{% endif %}</span>
        </div>
        <div class="stock-card-price">{{ stats.current|money }}</div>
        <div class="stock-card-change {{ 'side-buy' if stats.change >= 0 else 'side-sell' }}">
          {{ '+' if stats.change >= 0 else '' }}{{ stats.change|money }} ({{ '+' if stats.pct >= 0 else '' }}{{ "%.2f"|format(stats.pct) }}%)
        </div>
        <div class="stock-card-meta">
          <div class="stock-card-meta-item">
            <span class="stock-card-meta-label">{{ tr('currency_owner_label') }}</span>
            <span class="stock-card-meta-value">{{ s.owner_name }}</span>
          </div>
          <div class="stock-card-meta-item">
            <span class="stock-card-meta-label">{{ tr('market_cap_label') }}</span>
            <span class="stock-card-meta-value">{{ s.market_cap()|money }}</span>
          </div>
          <div class="stock-card-meta-item">
            <span class="stock-card-meta-label">{{ tr('owned_col') }}</span>
            <span class="stock-card-meta-value">{{ my_holdings.get(s.id, 0)|money }}</span>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>
  {% else %}<div class="empty">{{ tr('no_live_currencies') }}</div>{% endif %}
</div>

<div class="panel">
  <h2>{{ tr('trading_market') }}</h2>
  <p class="lede">{{ tr('trading_lede') }}</p>
  {% if stocks %}
  <form method="post" action="{{ url_for('place_order') }}" class="inline">
    <select name="stock_id">{% for s in stocks %}<option value="{{ s.id }}">{{ s.symbol }} {{ s.name }}</option>{% endfor %}</select>
    <select name="side"><option value="buy">{{ tr('buy') }}</option><option value="sell">{{ tr('sell') }}</option></select>
    <input name="price" type="text" inputmode="decimal" class="money-input" placeholder="{{ tr('price') }}" required style="width:110px;">
    <input name="quantity" type="number" min="1" placeholder="{{ tr('quantity') }}" required style="width:100px;">
    <button type="submit">{{ tr('execute_order') }}</button>
  </form>
  <p style="font-size:11px; color:var(--ink-dim); text-align:end; margin-top:6px;">{{ tr('trading_fee_market_note').format(fee=fee_percent) }}</p>
  {% else %}
  <div class="empty">{{ tr('no_stocks_offered') }}</div>
  {% endif %}

  <h3>{{ tr('open_orders') }}</h3>
  {% if orders %}
  {% set buy_count = orders|selectattr('side', 'equalto', 'buy')|list|length %}
  {% set sell_count = orders|selectattr('side', 'equalto', 'sell')|list|length %}
  <div id="ordersFilterTabs" style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px;">
    <button type="button" class="status-pill ok order-filter-btn" data-filter="all">{{ tr('filter_all') }} ({{ orders|length }})</button>
    <button type="button" class="status-pill unknown order-filter-btn" data-filter="buy">{{ tr('buy') }} ({{ buy_count }})</button>
    <button type="button" class="status-pill unknown order-filter-btn" data-filter="sell">{{ tr('sell') }} ({{ sell_count }})</button>
  </div>
  <table>
    <thead><tr><th>{{ tr('user_col') }}</th><th>{{ tr('company_col') }}</th><th>{{ tr('type_col') }}</th><th>{{ tr('price') }}</th><th>{{ tr('quantity') }}</th><th>{{ tr('owned_col') }}</th><th></th></tr></thead>
    <tbody>
    {% for o in orders %}
      <tr class="order-row" data-side="{{ o.side }}">
        <td data-label="{{ tr('user_col') }}">{{ o.user.username }}{{ vbadge(o.user)|safe }}</td>
        <td data-label="{{ tr('company_col') }}">{{ o.stock.symbol }} {{ o.stock.name }}</td>
        <td data-label="{{ tr('type_col') }}"><span class="{{ 'side-buy' if o.side == 'buy' else 'side-sell' }}">{{ tr('buy') if o.side == 'buy' else tr('sell') }}</span></td>
        <td data-label="{{ tr('price') }}">{{ o.price|money }}</td>
        <td data-label="{{ tr('quantity') }}">{{ o.quantity|money }}</td>
        <td data-label="{{ tr('owned_col') }}">{{ holdings_lookup.get(o.user_id, {}).get(o.stock_id, 0)|money }}</td>
        <td data-label="">
          {% if o.user_id == current_user.id or current_user.is_admin %}
          <form method="post" action="{{ url_for('cancel_order', order_id=o.id) }}"
                {% if current_user.is_admin and o.user_id != current_user.id %}class="confirm-form" data-confirm="{{ tr('confirm_cancel_order_admin') }}"{% endif %}>
            <button type="submit" class="danger" style="padding:5px 10px; font-size:12px;">{{ tr('cancel') }}</button>
          </form>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  <div id="noOrdersFilterResults" class="empty" style="display:none;">{{ tr('no_open_orders') }}</div>
  <script>
  (function () {
    var buttons = document.querySelectorAll('.order-filter-btn');
    var noResults = document.getElementById('noOrdersFilterResults');
    function applyFilter(filter) {
      var visibleCount = 0;
      document.querySelectorAll('.order-row').forEach(function (row) {
        var match = filter === 'all' || row.dataset.side === filter;
        row.style.display = match ? '' : 'none';
        if (match) visibleCount++;
      });
      if (noResults) noResults.style.display = visibleCount === 0 ? 'block' : 'none';
      buttons.forEach(function (b) {
        b.classList.toggle('ok', b.dataset.filter === filter);
        b.classList.toggle('unknown', b.dataset.filter !== filter);
      });
    }
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () { applyFilter(btn.dataset.filter); });
    });
  })();
  </script>
  {% else %}<div class="empty">{{ tr('no_open_orders') }}</div>{% endif %}
</div>

<div class="panel">
  <h2>{{ tr('my_trades_title') }}</h2>
  <p class="lede">{{ tr('my_trades_lede') }}</p>
</div>

<details class="activity-section">
  <summary>{{ tr('my_trades_title') }} <span class="count-badge">{{ my_trades|length }}</span></summary>
  <div class="activity-body">
    {% if my_trades %}
    <table>
      <thead><tr><th>{{ tr('company_col') }}</th><th>{{ tr('type_col') }}</th><th>{{ tr('price') }}</th><th>{{ tr('quantity') }}</th><th>{{ tr('total_col') }}</th><th>{{ tr('date_col') }}</th></tr></thead>
      <tbody>
      {% for t in my_trades %}
        {% set is_buy = t.buyer_id == current_user.id %}
        <tr>
          <td data-label="{{ tr('company_col') }}">{{ t.stock.symbol }} {{ t.stock.name }}</td>
          <td data-label="{{ tr('type_col') }}"><span class="{{ 'side-buy' if is_buy else 'side-sell' }}">{{ tr('buy') if is_buy else tr('sell') }}</span></td>
          <td data-label="{{ tr('price') }}">{{ t.price|money }}</td>
          <td data-label="{{ tr('quantity') }}">{{ t.quantity|money }}</td>
          <td data-label="{{ tr('total_col') }}">{{ t.total_value()|money }}</td>
          <td data-label="{{ tr('date_col') }}">{{ t.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_my_trades_yet') }}</div>{% endif %}
  </div>
</details>
"""

COMPANY_PROFILE_HTML = """
<div class="panel">
  <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
    <h2 style="margin:0;">{{ stock.symbol }} — {{ stock.name }}</h2>
    {% if stock.sector %}<span class="status-pill unknown">{{ stock.sector }}</span>{% endif %}
  </div>
  {% if stock.description %}<p class="lede" style="margin-top:10px;">{{ stock.description }}</p>{% endif %}
  <ul class="holdings-list" style="margin-top:12px;">
    {% if stock.owner_name %}<li><span>{{ tr('company_owner') }}</span><span class="qty">{{ stock.owner_name }}{% if stock.owner_account_id %} (#{{ stock.owner_account_id }}){% endif %}</span></li>{% endif %}
    <li><span>{{ tr('total_shares_stat') }}</span><span class="qty">{{ shares_outstanding|money }}</span></li>
    <li><span>{{ tr('listed_since_label') }}</span><span class="qty">{{ stock.listed_at.strftime("%Y-%m-%d") if stock.listed_at else "—" }}</span></li>
  </ul>
</div>

<div class="panel">
  <h2>{{ tr('ownership_breakdown_title') }}</h2>
  <ul class="holdings-list">
    <li><span>{{ tr('owner_share_label') }}</span><span class="qty">{{ ownership.owner_shares|money }} ({{ "%.1f"|format(ownership.owner_pct) }}%)</span></li>
    <li><span>{{ tr('gnid_share_label') }}</span><span class="qty">{{ ownership.gnid_shares|money }} ({{ "%.1f"|format(ownership.gnid_pct) }}%)</span></li>
    <li><span>{{ tr('market_share_label') }}</span><span class="qty">{{ ownership.market_shares|money }} ({{ "%.1f"|format(ownership.market_pct) }}%)</span></li>
    {% if stock.dividend_pct and stock.dividend_pct > 0 %}
    <li><span>{{ tr('dividend_pct_field') }}</span><span class="qty" style="color:var(--gold);">{{ stock.dividend_pct }}%</span></li>
    {% endif %}
  </ul>
  {% if stock.dividend_pct and stock.dividend_pct > 0 %}
  <p style="margin-top:10px; font-size:12px; color:var(--gold); font-weight:700;">{{ tr('dividend_friday_note') }}</p>
  {% endif %}
</div>

{% if stock.dividend_pct and stock.dividend_pct > 0 %}
<details class="activity-section">
  <summary>{{ tr('dividend_history_title') }} <span class="count-badge">{{ dividend_payouts|length }}</span></summary>
  <div class="activity-body">
    <p class="lede" style="margin-bottom:6px;">{{ tr('dividend_pct_field') }}: <strong style="color:var(--gold);">{{ stock.dividend_pct }}%</strong> — {{ tr('dividend_company_note') }}</p>
    <p style="margin-bottom:12px; font-size:12px; color:var(--gold); font-weight:700;">{{ tr('dividend_friday_note') }}</p>
    {% if dividend_payouts %}
    <table>
      <thead><tr><th>{{ tr('net_profit_label') }}</th><th>{{ tr('total_fund_label') }}</th><th>{{ tr('recipients_label') }}</th><th>{{ tr('date_col') }}</th></tr></thead>
      <tbody>
      {% for p in dividend_payouts %}
        <tr>
          <td data-label="{{ tr('net_profit_label') }}">{{ p.net_profit|money }}</td>
          <td data-label="{{ tr('total_fund_label') }}">{{ p.total_fund|money }}</td>
          <td data-label="{{ tr('recipients_label') }}">{{ p.recipients_count }}</td>
          <td data-label="{{ tr('date_col') }}">{{ p.created_at.strftime("%Y-%m-%d") }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_dividend_history_yet') }}</div>{% endif %}
  </div>
</details>
{% endif %}

<div class="panel">
  <div class="stat-grid">
    <div class="stat-card stat-hero">
      <div class="stat-label">{{ tr('current_price_label') }}</div>
      <div class="stat-value">{{ stats.current|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('price_change_label') }}</div>
      <div class="stat-value" style="color: {{ 'var(--green-ink)' if stats.change >= 0 else 'var(--red)' }};">
        {{ '+' if stats.change >= 0 else '' }}{{ stats.change|money }} ({{ '+' if stats.pct >= 0 else '' }}{{ "%.2f"|format(stats.pct) }}%)
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('opening_price_label') }}</div>
      <div class="stat-value">{{ stats.opening|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('high_price_label') }}</div>
      <div class="stat-value">{{ stats.high|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('low_price_label') }}</div>
      <div class="stat-value">{{ stats.low|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('market_cap_label') }}</div>
      <div class="stat-value">{{ market_cap|money }}</div>
    </div>
  </div>
</div>

<div class="panel">
  <h2>{{ tr('price_chart_title') }}</h2>
  {% if chart_points|length > 1 %}
  <div class="range-tabs" id="chartRangeTabs">
    <button type="button" class="range-tab" data-hours="1">1H</button>
    <button type="button" class="range-tab" data-hours="6">6H</button>
    <button type="button" class="range-tab" data-hours="24">1D</button>
    <button type="button" class="range-tab" data-hours="168">7D</button>
    <button type="button" class="range-tab" data-hours="720">30D</button>
    <button type="button" class="range-tab" data-hours="2160">3M</button>
    <button type="button" class="range-tab active" data-hours="0">{{ tr('range_all') }}</button>
  </div>
  <canvas id="priceChart" height="90"></canvas>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
  <script>
  (function () {
    var allPoints = {{ chart_points|tojson }}.map(function (p) { return { t: new Date(p.t), p: p.p }; });
    var ctx = document.getElementById('priceChart').getContext('2d');
    var chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: '{{ tr("current_price_label") }}',
          data: [],
          borderColor: '#D2AC5A',
          backgroundColor: 'rgba(201,162,75,0.12)',
          fill: true,
          tension: 0.15,
          pointRadius: 2,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#93A1B4' }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y: { ticks: { color: '#93A1B4' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
      }
    });

    function fmtLabel(d) {
      return (d.getMonth() + 1) + '-' + d.getDate() + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    }

    function renderRange(hours) {
      var points = allPoints;
      if (hours > 0) {
        var cutoff = new Date(Date.now() - hours * 3600 * 1000);
        var filtered = allPoints.filter(function (pt) { return pt.t >= cutoff; });
        // لو مفيش صفقات كفاية في المدى ده، نضيف آخر نقطة قبل المدى عشان الخط يبان صح من البداية
        if (filtered.length && filtered.length < allPoints.length) {
          var firstIdx = allPoints.indexOf(filtered[0]);
          if (firstIdx > 0) filtered = [allPoints[firstIdx - 1]].concat(filtered);
        }
        points = filtered.length ? filtered : allPoints.slice(-1);
      }
      chart.data.labels = points.map(function (pt) { return fmtLabel(pt.t); });
      chart.data.datasets[0].data = points.map(function (pt) { return pt.p; });
      chart.update();
    }

    var tabs = document.querySelectorAll('#chartRangeTabs .range-tab');
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        tabs.forEach(function (t) { t.classList.remove('active'); });
        tab.classList.add('active');
        renderRange(parseInt(tab.dataset.hours, 10));
      });
    });

    renderRange(0);
  })();
  </script>
  {% else %}
  <div class="empty">{{ tr('no_trades_yet') }}</div>
  {% endif %}
</div>

<div class="panel">
  <h2>{{ tr('trading_volume_title') }}</h2>
  <div class="stat-grid">
    <div class="stat-card"><div class="stat-label">{{ tr('total_shares_traded') }}</div><div class="stat-value">{{ volume.shares|money }}</div></div>
    <div class="stat-card"><div class="stat-label">{{ tr('total_trading_value') }}</div><div class="stat-value">{{ volume.value|money }}</div></div>
    <div class="stat-card"><div class="stat-label">{{ tr('transactions_count') }}</div><div class="stat-value">{{ volume.count }}</div></div>
    <div class="stat-card"><div class="stat-label">{{ tr('avg_price_label') }}</div><div class="stat-value">{{ volume.avg_price|money }}</div></div>
  </div>
</div>

<p style="font-size:11px; color:var(--ink-dim); margin-bottom:8px;">{{ tr('auto_price_move_hint') }}</p>
<details class="activity-section">
  <summary>{{ tr('market_activity_title') }} <span class="count-badge">{{ recent_trades|length }}</span></summary>
  <div class="activity-body">
    {% if recent_trades %}
    <table>
      <thead><tr><th>{{ tr('type_col') }}</th><th>{{ tr('quantity') }}</th><th>{{ tr('price') }}</th><th>{{ tr('date_col') }}</th></tr></thead>
      <tbody>
      {% for t in recent_trades %}
        <tr>
          <td data-label="{{ tr('type_col') }}">
            <span class="side-buy">{{ tr('ipo_source') if t.source == 'ipo' else tr('buy_side') }}</span>
          </td>
          <td data-label="{{ tr('quantity') }}">{{ t.quantity|money }}</td>
          <td data-label="{{ tr('price') }}">{{ t.price|money }}</td>
          <td data-label="{{ tr('date_col') }}">{{ t.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_activity_yet') }}</div>{% endif %}
  </div>
</details>

<details class="activity-section">
  <summary>{{ tr('shareholders_title') }} <span class="count-badge">{{ shareholders|length }}</span></summary>
  <div class="activity-body">
    {% if shareholders %}
    <table>
      <thead><tr><th>{{ tr('rank_col') }}</th><th>{{ tr('username') }}</th><th>{{ tr('quantity') }}</th><th>{{ tr('ownership_pct_col') }}</th><th>{{ tr('holdings_value_col') }}</th></tr></thead>
      <tbody>
      {% for h in shareholders %}
        <tr>
          <td data-label="{{ tr('rank_col') }}">#{{ loop.index }}</td>
          <td data-label="{{ tr('username') }}">{{ h.user.username }}{{ vbadge(h.user)|safe }}</td>
          <td data-label="{{ tr('quantity') }}">{{ h.quantity|money }}</td>
          <td data-label="{{ tr('ownership_pct_col') }}">{{ "%.2f"|format(h.quantity / shares_outstanding * 100 if shares_outstanding else 0) }}%</td>
          <td data-label="{{ tr('holdings_value_col') }}">{{ (h.quantity * stats.current)|money }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_shareholders_yet') }}</div>{% endif %}
  </div>
</details>
"""

GLOBAL_RANKINGS_HTML = """
<div class="panel">
  <h2>{{ tr('global_rankings_title') }}</h2>
  {% if rankings %}
  <table>
    <thead><tr><th>{{ tr('rank_col') }}</th><th>{{ tr('username') }}</th><th>{{ tr('company_col') }}</th><th>{{ tr('quantity') }}</th><th>{{ tr('ownership_pct_col') }}</th><th>{{ tr('holdings_value_col') }}</th></tr></thead>
    <tbody>
    {% for r in rankings %}
      <tr>
        <td data-label="{{ tr('rank_col') }}">#{{ loop.index }}</td>
        <td data-label="{{ tr('username') }}">{{ r.username }}{% if r.verified %} <span class="verified-badge" title="Verified">✅</span>{% endif %}</td>
        <td data-label="{{ tr('company_col') }}"><a href="{{ url_for('company_profile', stock_id=r.stock_id) }}" style="color:var(--gold);">{{ r.stock_name }}</a></td>
        <td data-label="{{ tr('quantity') }}">{{ r.quantity|money }}</td>
        <td data-label="{{ tr('ownership_pct_col') }}">{{ "%.2f"|format(r.pct) }}%</td>
        <td data-label="{{ tr('holdings_value_col') }}">{{ r.value|money }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_shareholders_yet') }}</div>{% endif %}
</div>
"""

ADMIN_ACTIVITY_HTML = """
<div class="panel">
  <h2>{{ tr('full_activity_title') }}</h2>
  <p class="lede">{{ tr('full_activity_lede') }}</p>
</div>

<details class="activity-section">
  <summary>{{ tr('section_deposits') }} <span class="count-badge">{{ deposits|length }}</span></summary>
  <div class="activity-body">
    {% if deposits %}
    <table>
      <thead><tr><th>{{ tr('user_col') }}</th><th>{{ tr('id_label') }}</th><th>{{ tr('telegram_label') }}</th><th>{{ tr('credited_col') }}</th><th>{{ tr('date_col') }}</th></tr></thead>
      <tbody>
      {% for d in deposits %}
        <tr>
          <td data-label="{{ tr('user_col') }}">{{ d.user.username if d.user else "—" }}{{ vbadge(d.user)|safe if d.user }}</td>
          <td data-label="{{ tr('id_label') }}">#{{ d.user.account_id if d.user else "—" }}</td>
          <td data-label="{{ tr('telegram_label') }}">{{ d.user.telegram_username|tglink(d.user.telegram_has_username, d.user.telegram_chat_id)|safe if d.user else "—" }}</td>
          <td data-label="{{ tr('credited_col') }}">{{ d.amount_credited|money }}</td>
          <td data-label="{{ tr('date_col') }}">{{ d.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_deposits_yet') }}</div>{% endif %}
  </div>
</details>

<details class="activity-section">
  <summary>{{ tr('section_withdrawals') }} <span class="count-badge">{{ withdrawals|length }}</span></summary>
  <div class="activity-body">
    {% if withdrawals %}
    <table>
      <thead><tr><th>{{ tr('username') }}</th><th>{{ tr('telegram_label') }}</th><th>{{ tr('amount') }}</th><th>{{ tr('date_col') }}</th><th>{{ tr('status_col') }}</th></tr></thead>
      <tbody>
      {% for w in withdrawals %}
        <tr>
          <td data-label="{{ tr('username') }}">{{ w.user.username }}{{ vbadge(w.user)|safe }}</td>
          <td data-label="{{ tr('telegram_label') }}">{{ w.user.telegram_username|tglink(w.user.telegram_has_username, w.user.telegram_chat_id)|safe }}</td>
          <td data-label="{{ tr('amount') }}">{{ w.amount|money }}</td>
          <td data-label="{{ tr('date_col') }}">{{ w.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
          <td data-label="{{ tr('status_col') }}">
            <span class="{{ 'side-buy' if w.status == 'done' else ('side-sell' if w.status in ['rejected', 'cancelled'] else '') }}">
              {{ tr('status_done') if w.status == 'done' else (tr('status_rejected') if w.status == 'rejected' else (tr('status_cancelled') if w.status == 'cancelled' else tr('status_pending'))) }}
            </span>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_withdrawals_yet') }}</div>{% endif %}
  </div>
</details>

<details class="activity-section">
  <summary>{{ tr('section_investments') }} <span class="count-badge">{{ investments|length }}</span></summary>
  <div class="activity-body">
    {% if investments %}
    <table>
      <thead><tr><th>{{ tr('username') }}</th><th>{{ tr('invested_col') }}</th><th>{{ tr('expected_payout_col') }}</th><th>{{ tr('matures_col') }}</th><th>{{ tr('status_col') }}</th></tr></thead>
      <tbody>
      {% for inv in investments %}
        <tr>
          <td data-label="{{ tr('username') }}">{{ inv.user.username }}{{ vbadge(inv.user)|safe }}</td>
          <td data-label="{{ tr('invested_col') }}">{{ inv.amount|money }}</td>
          <td data-label="{{ tr('expected_payout_col') }}">{{ inv.payout|money }}</td>
          <td data-label="{{ tr('matures_col') }}">{{ inv.matures_at.strftime("%Y-%m-%d %H:%M") }}</td>
          <td data-label="{{ tr('status_col') }}">
            <span class="{{ 'side-buy' if inv.status == 'paid' else 'side-sell' }}">{{ tr('status_paid') if inv.status == 'paid' else tr('status_active') }}</span>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_investments_at_all') }}</div>{% endif %}
  </div>
</details>

<details class="activity-section">
  <summary>{{ tr('section_loans') }} <span class="count-badge">{{ loans|length }}</span></summary>
  <div class="activity-body">
    {% if loans %}
    <table>
      <thead><tr><th>{{ tr('username') }}</th><th>{{ tr('telegram_label') }}</th><th>{{ tr('amount') }}</th><th>{{ tr('term_col') }}</th><th>{{ tr('repay_amount_col') }}</th><th>{{ tr('due_date_col') }}</th><th>{{ tr('loan_reason_col') }}</th><th>{{ tr('date_col') }}</th><th>{{ tr('status_col') }}</th></tr></thead>
      <tbody>
      {% for l in loans %}
        <tr>
          <td data-label="{{ tr('username') }}">{{ l.user.username }}{{ vbadge(l.user)|safe }}</td>
          <td data-label="{{ tr('telegram_label') }}">{{ l.user.telegram_username|tglink(l.user.telegram_has_username, l.user.telegram_chat_id)|safe }}</td>
          <td data-label="{{ tr('amount') }}">{{ l.amount|money }}</td>
          <td data-label="{{ tr('term_col') }}">{{ l.term_days }} {{ tr('loan_term_option') }} (+{{ l.interest_pct|int }}%)</td>
          <td data-label="{{ tr('repay_amount_col') }}">{{ l.repay_amount|money if l.repay_amount else "—" }}</td>
          <td data-label="{{ tr('due_date_col') }}">{{ l.due_date.strftime("%Y-%m-%d") if l.due_date else "—" }}</td>
          <td data-label="{{ tr('loan_reason_col') }}">{{ l.reason or "—" }}</td>
          <td data-label="{{ tr('date_col') }}">{{ l.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
          <td data-label="{{ tr('status_col') }}">
            <span class="{{ 'side-buy' if l.status in ['approved','repaid'] else ('side-sell' if l.status == 'rejected' else '') }}">
              {{ tr('status_repaid') if l.status == 'repaid' else (tr('status_approved') if l.status == 'approved' else (tr('status_rejected') if l.status == 'rejected' else tr('status_pending'))) }}
            </span>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_loans_at_all') }}</div>{% endif %}
  </div>
</details>

<details class="activity-section">
  <summary>{{ tr('section_trades') }} <span class="count-badge">{{ trades|length }}</span></summary>
  <div class="activity-body">
    {% if trades %}
    <table>
      <thead><tr><th>{{ tr('company_col') }}</th><th>{{ tr('trade_side_col') }}</th><th>{{ tr('buyer_col') }}</th><th>{{ tr('seller_col') }}</th><th>{{ tr('quantity') }}</th><th>{{ tr('price') }}</th><th>{{ tr('date_col') }}</th></tr></thead>
      <tbody>
      {% for t in trades %}
        <tr>
          <td data-label="{{ tr('company_col') }}"><a href="{{ url_for('company_profile', stock_id=t.stock_id) }}" style="color:var(--gold);">{{ t.stock.symbol }} {{ t.stock.name }}</a></td>
          <td data-label="{{ tr('trade_side_col') }}"><span class="side-buy">{{ tr('ipo_source') if t.source == 'ipo' else tr('buy_side') }}</span></td>
          <td data-label="{{ tr('buyer_col') }}">{{ t.buyer.username if t.buyer else tr('deleted_user_label') }}{{ vbadge(t.buyer)|safe if t.buyer }}</td>
          <td data-label="{{ tr('seller_col') }}">{{ t.seller.username if t.seller else (tr('ipo_source') if t.source == 'ipo' else tr('deleted_user_label')) }}{{ vbadge(t.seller)|safe if t.seller }}</td>
          <td data-label="{{ tr('quantity') }}">{{ t.quantity|money }}</td>
          <td data-label="{{ tr('price') }}">{{ t.price|money }}</td>
          <td data-label="{{ tr('date_col') }}">{{ t.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_trades_at_all') }}</div>{% endif %}
  </div>
</details>

<details class="activity-section">
  <summary>{{ tr('section_admin_actions') }} <span class="count-badge">{{ admin_actions|length }}</span></summary>
  <div class="activity-body">
    {% if admin_actions %}
    <table>
      <thead><tr><th>{{ tr('admin_col') }}</th><th>{{ tr('performed_by_col') }}</th><th>{{ tr('action_col') }}</th><th>{{ tr('target_user_col') }}</th><th>{{ tr('amount') }}</th><th>{{ tr('date_col') }}</th></tr></thead>
      <tbody>
      {% for log in admin_actions %}
        <tr>
          <td data-label="{{ tr('admin_col') }}">{{ log.admin_username }}</td>
          <td data-label="{{ tr('performed_by_col') }}">
            <span class="status-pill {{ 'ok' if log.actor_role == 'admin' else 'unknown' }}">{{ tr('role_admin') if log.actor_role == 'admin' else tr('role_mod') }}</span>
          </td>
          <td data-label="{{ tr('action_col') }}">
            <span class="{{ 'side-buy' if log.action in ['balance_add', 'shares_to_treasury', 'stock_add', 'loan_approve', 'investment_add_manual', 'withdraw_done', 'withdraw_auto_sent', 'user_unfreeze', 'company_approve', 'dividend_distribute', 'currency_approve', 'currency_revenue', 'stock_resume'] else ('side-sell' if log.action in ['balance_subtract', 'user_delete', 'shares_from_treasury', 'loan_reject', 'stock_delete', 'stock_delete_refund', 'withdraw_reject', 'investment_delete', 'treasury_payout', 'order_cancelled_by_admin', 'company_reject', 'currency_reject', 'stock_suspend'] else '') }}">
              {{ tr('action_' + log.action) }}
            </span>
          </td>
          <td data-label="{{ tr('target_user_col') }}">{{ log.target_username }}{% if log.target_account_id %} (#{{ log.target_account_id }}){% endif %}</td>
          <td data-label="{{ tr('amount') }}">{{ log.amount|money if log.amount is not none else "—" }}</td>
          <td data-label="{{ tr('date_col') }}">{{ log.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_admin_actions_yet') }}</div>{% endif %}
  </div>
</details>
"""

INVEST_HTML = """
<div class="panel" style="max-width:520px;">
  <h2>{{ tr('investment_title') }}</h2>
  <p class="lede">{{ tr('investment_lede') }}</p>
  <ul class="holdings-list" style="margin-bottom:16px;">
    {% for days, pct in investment_terms.items() %}
    <li><span>{{ days }} {{ tr('days_word') }}</span><span class="qty">+{{ pct }}%</span></li>
    {% endfor %}
    <li><span>{{ tr('investment_min') }}</span><span class="qty">{{ min_amount|money }}</span></li>
  </ul>
  <form method="post">
    <div><label>{{ tr('invest_amount_label') }}</label><input name="amount" type="text" inputmode="decimal" class="money-input" required></div>
    <div>
      <label>{{ tr('investment_terms') }}</label>
      <select name="term_days">
        {% for days, pct in investment_terms.items() %}
        <option value="{{ days }}">{{ days }} {{ tr('days_word') }} — +{{ pct }}%</option>
        {% endfor %}
      </select>
    </div>
    <button type="submit">{{ tr('invest_btn') }}</button>
  </form>
</div>

<div class="panel">
  <h2>{{ tr('my_investments') }}</h2>
  {% if investments %}
  <table>
    <thead><tr><th>{{ tr('invested_col') }}</th><th>{{ tr('investment_rate') }}</th><th>{{ tr('expected_payout_col') }}</th><th>{{ tr('matures_col') }}</th><th>{{ tr('status_col') }}</th></tr></thead>
    <tbody>
    {% for inv in investments %}
      <tr>
        <td data-label="{{ tr('invested_col') }}">{{ inv.amount|money }}</td>
        <td data-label="{{ tr('investment_rate') }}">+{{ inv.rate_percent|money }}%</td>
        <td data-label="{{ tr('expected_payout_col') }}">{{ inv.payout|money }}</td>
        <td data-label="{{ tr('matures_col') }}">{{ inv.matures_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="{{ tr('status_col') }}">
          <span class="{{ 'side-buy' if inv.status == 'paid' else 'side-sell' }}">{{ tr('status_paid') if inv.status == 'paid' else tr('status_active') }}</span>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_investments_yet') }}</div>{% endif %}
</div>
"""

FEATURE_DISABLED_HTML = """
<div class="panel" style="max-width:480px; text-align:center;">
  <h2>🚧 {{ tr('feature_under_update_title') }}</h2>
  <p class="lede">{{ tr('feature_under_update_body') }}</p>
</div>
"""

COMPANY_APPLY_HTML = """
<div class="panel" style="max-width:560px;">
  <h2>{{ tr('company_apply_title') }}</h2>
  <p class="lede">{{ tr('company_apply_lede') }}</p>
  <ul class="holdings-list" style="margin-bottom:16px;">
    <li><span>{{ tr('company_owner_share_label') }}</span><span class="qty">{{ owner_pct }}%</span></li>
    <li><span>{{ tr('company_gnid_share_label') }}</span><span class="qty">{{ gnid_pct }}%</span></li>
    <li><span>{{ tr('company_market_share_label') }}</span><span class="qty">{{ market_pct }}%</span></li>
  </ul>
  <form method="post">
    <div><label>{{ tr('company_name_label') }}</label><input name="company_name" required></div>
    <div><label>{{ tr('company_symbol_label') }}</label><input name="symbol" maxlength="20" required></div>
    <div><label>{{ tr('factory_link_label') }}</label><input name="factory_link" placeholder="https://diplomacia.com.tr/work/factory/..." required></div>
    <div><label>{{ tr('company_level_label') }}</label><input name="level" type="number" min="0" required></div>
    <div><label>{{ tr('company_capital_label') }}</label><input name="capital" type="text" inputmode="decimal" class="money-input" required></div>
    <div><label>{{ tr('company_daily_production_label') }}</label><input name="daily_production" type="text" inputmode="decimal" class="money-input" required></div>
    <button type="submit">{{ tr('company_apply_btn') }}</button>
  </form>
</div>

<div class="panel">
  <h2>{{ tr('my_company_requests') }}</h2>
  {% if my_requests %}
  <table>
    <thead><tr><th>{{ tr('company_name_label') }}</th><th>{{ tr('company_level_label') }}</th><th>{{ tr('valuation_col') }}</th><th>{{ tr('date_col') }}</th><th>{{ tr('status_col') }}</th></tr></thead>
    <tbody>
    {% for r in my_requests %}
      <tr>
        <td data-label="{{ tr('company_name_label') }}">{{ r.symbol }} {{ r.company_name }}</td>
        <td data-label="{{ tr('company_level_label') }}">{{ r.level }}</td>
        <td data-label="{{ tr('valuation_col') }}">{{ r.computed_valuation|money if r.computed_valuation else "—" }}</td>
        <td data-label="{{ tr('date_col') }}">{{ r.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="{{ tr('status_col') }}">
          <span class="{{ 'side-buy' if r.status == 'approved' else ('side-sell' if r.status == 'rejected' else '') }}">
            {{ tr('status_approved') if r.status == 'approved' else (tr('status_rejected') if r.status == 'rejected' else tr('status_pending')) }}
          </span>
          {% if r.status == 'rejected' and r.reject_reason %}<div style="font-size:11px; color:var(--ink-dim); margin-top:4px;">{{ r.reject_reason }}</div>{% endif %}
          {% if r.status == 'approved' and r.stock %}<div style="margin-top:4px;"><a href="{{ url_for('company_profile', stock_id=r.stock_id) }}" style="color:var(--gold); font-size:12px;">{{ tr('view_company_btn') }} →</a></div>{% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_company_requests_yet') }}</div>{% endif %}
</div>
"""

CURRENCY_APPLY_HTML = """
<div class="panel" style="max-width:560px;">
  <h2>{{ tr('currency_apply_title') }}</h2>
  <p class="lede">{{ tr('currency_apply_lede') }}</p>
  <form method="post">
    <div><label>{{ tr('currency_name_label') }}</label><input name="currency_name" required></div>
    <div><label>{{ tr('currency_symbol_label') }}</label><input name="symbol" maxlength="20" required></div>
    <div><label>{{ tr('currency_report_label') }}</label><textarea name="report_text" rows="6" required></textarea></div>
    <button type="submit">{{ tr('currency_apply_btn') }}</button>
  </form>
</div>

<div class="panel">
  <h2>{{ tr('my_currency_requests') }}</h2>
  {% if my_requests %}
  <table class="stacked-always">
    <thead><tr><th>{{ tr('currency_name_label') }}</th><th>{{ tr('date_col') }}</th><th>{{ tr('status_col') }}</th></tr></thead>
    <tbody>
    {% for r in my_requests %}
      <tr>
        <td data-label="{{ tr('currency_name_label') }}">{{ r.symbol }} {{ r.currency_name }}</td>
        <td data-label="{{ tr('date_col') }}">{{ r.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="{{ tr('status_col') }}">
          <span class="{{ 'side-buy' if r.status == 'approved' else ('side-sell' if r.status == 'rejected' else '') }}">
            {{ tr('status_approved') if r.status == 'approved' else (tr('status_rejected') if r.status == 'rejected' else tr('status_pending')) }}
          </span>
          {% if r.status == 'rejected' and r.reject_reason %}<div style="font-size:11px; color:var(--ink-dim); margin-top:4px;">{{ r.reject_reason }}</div>{% endif %}
          {% if r.status == 'approved' and r.stock %}<div style="margin-top:4px;"><a href="{{ url_for('company_profile', stock_id=r.stock_id) }}" style="color:var(--gold); font-size:12px;">{{ tr('view_currency_btn') }} →</a></div>{% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_currency_requests_yet') }}</div>{% endif %}
</div>
"""

DEBTS_HTML = """
<div class="panel" style="max-width:520px;">
  <h2>{{ tr('debts_title') }}</h2>
  <p class="lede">{{ tr('debts_request_lede') }}</p>


  <h3 style="margin-top:0; border-top:none; padding-top:0;">{{ tr('loan_terms_title') }}</h3>
  <ul class="holdings-list" style="margin-bottom:16px;">
    {% for days, pct in loan_terms.items() %}
    <li><span>{{ days }} {{ tr('loan_term_option') }}</span><span class="qty">+{{ pct }}%</span></li>
    {% endfor %}
  </ul>
  <p style="font-size:12px; color:var(--red-ink); margin-bottom:16px;">⚠️ {{ tr('loan_default_warning') }}</p>

  {% if current_user.telegram_verified %}
  <form method="post">
    <div><label>{{ tr('loan_amount_label') }}</label><input name="amount" type="text" inputmode="decimal" class="money-input" required></div>
    <div>
      <label>{{ tr('loan_term_label') }}</label>
      <select name="term_days">
        {% for days, pct in loan_terms.items() %}
        <option value="{{ days }}">{{ days }} {{ tr('loan_term_option') }} — +{{ pct }}%</option>
        {% endfor %}
      </select>
    </div>
    <div><label>{{ tr('loan_reason_label') }}</label><textarea name="reason" rows="2" placeholder="{{ tr('loan_reason_placeholder') }}"></textarea></div>
    <button type="submit">{{ tr('submit_loan_btn') }}</button>
  </form>
  {% else %}
  <div class="status-pill" style="display:block; padding:12px 14px; margin-top:10px;">
    🔒 {{ tr('loan_verify_required_notice') }}
    <a href="{{ url_for('settings') }}#verify-panel" style="color:var(--gold); font-weight:700;">{{ tr('telegram_verify_title') }}</a>
  </div>
  {% endif %}
  {% if contacts %}
  <p class="lede" style="margin-top:14px;">{{ tr('debts_lede') }}</p>
  <ul class="holdings-list">
    {% for c in contacts %}
    <li><span>{{ tr('debts_contact_label') }}</span><span class="qty">@{{ c }}</span></li>
    {% endfor %}
  </ul>
  {% endif %}
</div>

<div class="panel">
  <h2>{{ tr('my_loan_requests') }}</h2>
  {% if loans %}
  <table>
    <thead><tr><th>{{ tr('amount') }}</th><th>{{ tr('term_col') }}</th><th>{{ tr('repay_amount_col') }}</th><th>{{ tr('due_date_col') }}</th><th>{{ tr('status_col') }}</th><th></th></tr></thead>
    <tbody>
    {% for l in loans %}
      <tr>
        <td data-label="{{ tr('amount') }}">{{ l.amount|money }}</td>
        <td data-label="{{ tr('term_col') }}">{{ l.term_days }} {{ tr('loan_term_option') }} (+{{ l.interest_pct|int }}%)</td>
        <td data-label="{{ tr('repay_amount_col') }}">{{ l.repay_amount|money if l.repay_amount else "—" }}</td>
        <td data-label="{{ tr('due_date_col') }}">{{ l.due_date.strftime("%Y-%m-%d") if l.due_date else "—" }}</td>
        <td data-label="{{ tr('status_col') }}">
          <span class="{{ 'side-buy' if l.status in ['approved','repaid'] else ('side-sell' if l.status == 'rejected' else '') }}">
            {{ tr('status_repaid') if l.status == 'repaid' else (tr('status_approved') if l.status == 'approved' else (tr('status_rejected') if l.status == 'rejected' else tr('status_pending'))) }}
          </span>
        </td>
        <td data-label="">
          {% if l.status == 'approved' %}
          <form method="post" action="{{ url_for('repay_loan', loan_id=l.id) }}">
            <button type="submit" class="buy" style="padding:6px 12px; font-size:12px;">{{ tr('repay_now_btn') }}</button>
          </form>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_loan_requests_yet') }}</div>{% endif %}
</div>
"""

ADMIN_LOANS_HTML = """
{% macro loans_table(loans, empty_msg) %}
  {% if loans %}
  <table class="stacked-always">
    <thead><tr><th>{{ tr('id_label') }}</th><th>{{ tr('username') }}</th><th>{{ tr('telegram_label') }}</th><th>{{ tr('amount') }}</th><th>{{ tr('term_col') }}</th><th>{{ tr('repay_amount_col') }}</th><th>{{ tr('due_date_col') }}</th><th>{{ tr('loan_reason_col') }}</th><th>{{ tr('date_col') }}</th><th>{{ tr('status_col') }}</th><th></th></tr></thead>
    <tbody>
    {% for l in loans %}
      <tr>
        <td data-label="{{ tr('id_label') }}">#{{ l.user.account_id }}</td>
        <td data-label="{{ tr('username') }}">{{ l.user.username }}{{ vbadge(l.user)|safe }}</td>
        <td data-label="{{ tr('telegram_label') }}">{{ l.user.telegram_username|tglink(l.user.telegram_has_username, l.user.telegram_chat_id)|safe }}</td>
        <td data-label="{{ tr('amount') }}">{{ l.amount|money }}</td>
        <td data-label="{{ tr('term_col') }}">{{ l.term_days }} {{ tr('loan_term_option') }} (+{{ l.interest_pct|int }}%)</td>
        <td data-label="{{ tr('repay_amount_col') }}">{{ l.repay_amount|money if l.repay_amount else "—" }}</td>
        <td data-label="{{ tr('due_date_col') }}">{{ l.due_date.strftime("%Y-%m-%d") if l.due_date else "—" }}</td>
        <td data-label="{{ tr('loan_reason_col') }}">{{ l.reason or "—" }}</td>
        <td data-label="{{ tr('date_col') }}">{{ l.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="{{ tr('status_col') }}">
          <span class="{{ 'side-buy' if l.status in ['approved','repaid'] else ('side-sell' if l.status == 'rejected' else '') }}">
            {{ tr('status_repaid') if l.status == 'repaid' else (tr('status_approved') if l.status == 'approved' else (tr('status_rejected') if l.status == 'rejected' else tr('status_pending'))) }}
          </span>
        </td>
        <td data-label="">
          {% if l.status == 'pending' %}
          <form method="post" action="{{ url_for('admin_loan_approve', loan_id=l.id) }}" class="inline" style="gap:6px;">
            <button type="submit" class="buy" style="padding:6px 12px; font-size:12px;">{{ tr('approve_btn') }}</button>
          </form>
          <form method="post" action="{{ url_for('admin_loan_reject', loan_id=l.id) }}" style="margin-top:6px;">
            <button type="submit" class="danger" style="padding:6px 12px; font-size:12px;">{{ tr('reject_btn') }}</button>
          </form>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ empty_msg }}</div>{% endif %}
{% endmacro %}
<div class="panel">
  <h2>{{ tr('admin_loans_title') }}</h2>
  <p class="lede">{{ tr('admin_loans_lede') }}</p>

  <h3 style="margin-top:22px;">{{ tr('admin_loans_pending_title') }}{% if pending_loans %} ({{ pending_loans|length }}){% endif %}</h3>
  {{ loans_table(pending_loans, tr('no_pending_loans')) }}

  <h3 style="margin-top:26px;">{{ tr('admin_loans_history_title') }}</h3>
  <div id="loanHistoryTabs" style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px;">
    <button type="button" class="status-pill ok loan-tab-btn" data-tab="loan-tab-approved">{{ tr('admin_loans_approved_title') }}{% if approved_loans %} ({{ approved_loans|length }}){% endif %}</button>
    <button type="button" class="status-pill unknown loan-tab-btn" data-tab="loan-tab-repaid">{{ tr('admin_loans_repaid_title') }}{% if repaid_loans %} ({{ repaid_loans|length }}){% endif %}</button>
    <button type="button" class="status-pill unknown loan-tab-btn" data-tab="loan-tab-rejected">{{ tr('admin_loans_rejected_title') }}{% if rejected_loans %} ({{ rejected_loans|length }}){% endif %}</button>
  </div>

  <div id="loan-tab-approved" class="loan-tab-pane">
    {{ loans_table(approved_loans, tr('no_approved_loans')) }}
  </div>
  <div id="loan-tab-repaid" class="loan-tab-pane" hidden>
    {{ loans_table(repaid_loans, tr('no_repaid_loans')) }}
  </div>
  <div id="loan-tab-rejected" class="loan-tab-pane" hidden>
    {{ loans_table(rejected_loans, tr('no_rejected_loans')) }}
  </div>
</div>

<script>
(function () {
  var buttons = document.querySelectorAll('.loan-tab-btn');
  buttons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var target = btn.dataset.tab;
      document.querySelectorAll('.loan-tab-pane').forEach(function (pane) {
        pane.hidden = (pane.id !== target);
      });
      buttons.forEach(function (b) {
        b.classList.toggle('ok', b === btn);
        b.classList.toggle('unknown', b !== btn);
      });
    });
  });
})();
</script>
"""

ADMIN_VAULT_HISTORY_HTML = """
<div class="panel">
  <h2>{{ tr('vault_history_title') }}</h2>
  <p class="lede">{{ tr('vault_history_lede') }}</p>
  {% if error %}
  <div class="empty">{{ error }}</div>
  {% elif entries %}
  <table>
    <thead><tr><th>{{ tr('date_col') }}</th><th>{{ tr('vault_history_direction_col') }}</th><th>{{ tr('amount') }}</th><th>{{ tr('vault_history_counterparty_col') }}</th><th>{{ tr('vault_history_matched_account_col') }}</th></tr></thead>
    <tbody>
    {% for e in entries %}
      <tr>
        <td data-label="{{ tr('date_col') }}">{{ e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else "—" }}</td>
        <td data-label="{{ tr('vault_history_direction_col') }}">
          <span class="{{ 'side-buy' if e.type == 'income' else 'side-sell' }}">
            {{ ('⬇️ ' + tr('vault_history_in')) if e.type == 'income' else ('⬆️ ' + tr('vault_history_out')) }}
          </span>
        </td>
        <td data-label="{{ tr('amount') }}">
          <span class="{{ 'side-buy' if e.type == 'income' else 'side-sell' }}">{{ '+' if e.type == 'income' else '-' }}{{ e.amount|money }}</span>
        </td>
        <td data-label="{{ tr('vault_history_counterparty_col') }}">{{ e.counterparty_name }}</td>
        <td data-label="{{ tr('vault_history_matched_account_col') }}">
          {% if e.category == 'transfer_in' %}
            {% if e.matched_user %}#{{ e.matched_user.account_id }} — {{ e.matched_user.username }}{{ vbadge(e.matched_user)|safe }}
            {% elif e.refunded %}<span style="color:var(--gold);">{{ tr('vault_history_refunded') }}</span>
            {% else %}<span style="color:var(--red);">{{ tr('vault_history_no_match') }}</span>{% endif %}
          {% else %}—{% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  <div class="inline" style="margin-top:14px; gap:8px;">
    {% if page_num > 1 %}<a href="{{ url_for('admin_vault_history', page=page_num-1) }}" class="btn" style="text-decoration:none;">← {{ tr('prev_page') }}</a>{% endif %}
    <a href="{{ url_for('admin_vault_history', page=page_num+1) }}" class="btn" style="text-decoration:none;">{{ tr('next_page') }} →</a>
  </div>
  {% else %}<div class="empty">{{ tr('no_treasury_entries') }}</div>{% endif %}
</div>
"""

ADMIN_TREASURY_HTML = """
<div class="panel">
  <h2>{{ tr('treasury_title') }}</h2>
  <p class="lede">{{ tr('treasury_lede') }} ({{ fee_percent }}% {{ tr('trading_fee_note') }})</p>
  <div class="stat-grid">
    <div class="stat-card stat-hero">
      <div class="stat-label">{{ tr('treasury_balance_label') }}</div>
      <div class="stat-value">{{ balance|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('treasury_stocks_value_label') }}</div>
      <div class="stat-value">{{ stocks_value|money }}</div>
    </div>
    {% if vault %}
    <div class="stat-card">
      <div class="stat-label">{{ tr('vault_ingame_balance_label') }}</div>
      <div class="stat-value">{{ vault.last_balance|money }}</div>
    </div>
    {% endif %}
    <div class="stat-card">
      <div class="stat-label">{{ tr('treasury_total_entries') }}</div>
      <div class="stat-value">{{ entries|length }}</div>
    </div>
  </div>
  <a href="{{ url_for('admin_vault_history') }}" class="btn" style="text-decoration:none; display:inline-block; margin-top:16px;">📜 {{ tr('vault_history_title') }} →</a>
</div>

<div class="panel">
  <h2>{{ tr('bank_liabilities_title') }}</h2>
  <p class="lede">{{ tr('bank_liabilities_lede') }}</p>
  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-label">{{ tr('total_invested_active_label') }}</div>
      <div class="stat-value">{{ total_invested_active|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('total_investment_payout_due_label') }}</div>
      <div class="stat-value">{{ total_investment_payout_due|money }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{{ tr('total_loans_owed_label') }}</div>
      <div class="stat-value">{{ total_loans_owed|money }}</div>
    </div>
  </div>
</div>

{% if current_user.is_admin %}
<div class="panel" style="max-width:480px;">
  <h2>{{ tr('treasury_funds_transfer_title') }}</h2>
  <p class="lede">{{ tr('treasury_funds_transfer_lede') }}</p>
  <form method="post" action="{{ url_for('admin_treasury_transfer_funds') }}">
    <div><label>{{ tr('target_account_id') }}</label><input name="account_id" required></div>
    <div><label>{{ tr('amount') }}</label><input name="amount" type="text" inputmode="decimal" class="money-input" required></div>
    <button type="submit">{{ tr('transfer_shares_btn') }}</button>
  </form>
</div>
{% endif %}

<div class="panel" style="max-width:480px;">
  <h2>{{ tr('treasury_stocks_title') }}</h2>
  <p class="lede">{{ tr('treasury_stocks_lede') }}</p>
  {% if current_user.is_admin %}
  <form method="post" action="{{ url_for('admin_treasury_transfer_shares') }}">
    <div>
      <label>{{ tr('stock_label') }}</label>
      <select name="stock_id">
        {% for s in stocks %}<option value="{{ s.id }}">{{ s.symbol }} {{ s.name }} — {{ tr('available') }}: {{ s.admin_supply|money }} / {{ tr('treasury_holds_label') }}: {{ s.gnid_shares|money }}</option>{% endfor %}
      </select>
    </div>
    <div>
      <label>{{ tr('transfer_direction_label') }}</label>
      <select name="direction">
        <option value="to_treasury">{{ tr('to_treasury_option') }}</option>
        <option value="from_treasury">{{ tr('from_treasury_option') }}</option>
      </select>
    </div>
    <div><label>{{ tr('quantity') }}</label><input name="quantity" type="number" min="1" required></div>
    <button type="submit">{{ tr('transfer_shares_btn') }}</button>
  </form>
  {% else %}
  <p class="lede">{{ tr('mods_view_only_note') }}</p>
  {% endif %}
</div>

<div class="panel">
  <h2>{{ tr('treasury_holdings_title') }}</h2>
  {% if treasury_holdings %}
  <table>
    <thead><tr><th>{{ tr('company_col') }}</th><th>{{ tr('quantity') }}</th><th>{{ tr('current_price_label') }}</th><th>{{ tr('holdings_value_col') }}</th></tr></thead>
    <tbody>
    {% for h in treasury_holdings %}
      <tr>
        <td data-label="{{ tr('company_col') }}"><a href="{{ url_for('company_profile', stock_id=h.stock.id) }}" style="color:var(--gold);">{{ h.stock.symbol }} {{ h.stock.name }}</a></td>
        <td data-label="{{ tr('quantity') }}">{{ h.stock.gnid_shares|money }}</td>
        <td data-label="{{ tr('current_price_label') }}">{{ h.price|money }}</td>
        <td data-label="{{ tr('holdings_value_col') }}">{{ h.value|money }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_treasury_holdings') }}</div>{% endif %}
</div>

<details class="activity-section">
  <summary>{{ tr('treasury_log_title') }} <span class="count-badge">{{ entries|length }}</span></summary>
  <div class="activity-body">
    {% if entries %}
    <table>
      <thead><tr><th>{{ tr('amount') }}</th><th>{{ tr('source_col') }}</th><th>{{ tr('company_col') }}</th><th>{{ tr('date_col') }}</th></tr></thead>
      <tbody>
      {% for e in entries %}
        <tr>
          <td data-label="{{ tr('amount') }}">{{ e.amount|money }}</td>
          <td data-label="{{ tr('source_col') }}">{{ tr('fee_source_loan_repayment') if e.source == 'loan_repayment' else (tr('fee_source_loan_repayment_auto') if e.source == 'loan_repayment_auto' else (tr('fee_source_admin_payout') if e.source == 'admin_payout' else tr('fee_source_trade'))) }}</td>
          <td data-label="{{ tr('company_col') }}">
            {% if e.trade %}<a href="{{ url_for('company_profile', stock_id=e.trade.stock_id) }}" style="color:var(--gold);">{{ e.trade.stock.symbol }} {{ e.trade.stock.name }}</a>{% else %}—{% endif %}
          </td>
          <td data-label="{{ tr('date_col') }}">{{ e.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_treasury_entries') }}</div>{% endif %}
  </div>
</details>
"""

SETTINGS_HTML = """
<div class="panel" id="password-panel" style="max-width:480px;">
  <h2>{{ tr('change_password_section') }}</h2>
  <form method="post" action="{{ url_for('settings_change_password') }}">
    <div><label>{{ tr('current_password_label') }}</label><input name="current_password" type="password" required></div>
    <div><label>{{ tr('new_password_label') }}</label><input name="new_password" type="password" required></div>
    <div><label>{{ tr('confirm_new_password_label') }}</label><input name="confirm_password" type="password" required></div>
    <button type="submit">{{ tr('save_password_settings_btn') }}</button>
  </form>
</div>

<div class="panel" id="username-panel" style="max-width:480px;">
  <h2>{{ tr('change_account_username_section') }}</h2>
  {% if current_user.username_changed %}
  <p class="lede">{{ tr('account_username_locked_note') }} <b style="color:var(--gold);">{{ current_user.username }}</b> 🔒</p>
  {% elif current_user.telegram_verified %}
  <p class="lede">{{ tr('account_username_locked_verified_note') }} <b style="color:var(--gold);">{{ current_user.username }}</b> 🔒</p>
  {% else %}
  <p class="lede">{{ tr('change_account_username_lede') }}</p>
  <form method="post" action="{{ url_for('settings_change_username') }}">
    <div><label>{{ tr('new_account_username_label') }}</label><input name="username" value="{{ current_user.username }}" required></div>
    <button type="submit">{{ tr('save_account_username_btn') }}</button>
  </form>
  {% endif %}
</div>

<div class="panel" id="telegram-panel" style="max-width:480px;">
  <h2>{{ tr('change_telegram_section') }}</h2>
  {% if current_user.telegram_verified %}
  <p class="lede">{{ tr('telegram_locked_note') }}</p>
  <ul class="holdings-list">
    <li><span>{{ tr('telegram_username_label') }}</span><span class="qty">@{{ current_user.telegram_username }} 🔒</span></li>
  </ul>
  {% else %}
  <form method="post" action="{{ url_for('settings_change_telegram') }}">
    <div><label>{{ tr('telegram_username_label') }}</label><input name="telegram_username" value="{{ current_user.telegram_username }}" pattern="^@?[A-Za-z][A-Za-z0-9_]{4,31}$" title="{{ tr('flash_telegram_invalid_format') }}" required></div>
    <button type="submit">{{ tr('save_telegram_btn') }}</button>
  </form>
  {% endif %}
</div>

{% if not (current_user.is_admin or current_user.is_mod) %}
<div class="panel" id="verify-panel" style="max-width:480px;">
  <h2>{{ tr('telegram_verify_title') }}</h2>
  <p class="lede">{{ tr('telegram_verify_lede') }}</p>
  <p style="margin-bottom:14px;">
    <span class="status-pill {{ 'ok' if current_user.telegram_verified else 'unknown' }}">
      {{ tr('telegram_verify_status_verified') if current_user.telegram_verified else tr('telegram_verify_status_not_verified') }}
    </span>
  </p>
  {% if not current_user.telegram_verified %}
    {% if not bot_username %}
    <div class="empty">{{ tr('telegram_bot_not_configured') }}</div>
    {% else %}
    <form method="post" action="{{ url_for('settings_generate_verify_code') }}">
      <button type="submit">{{ tr('telegram_verify_generate_btn') }}</button>
    </form>
    {% if verify_link %}
    <ul class="holdings-list" style="margin-top:14px;">
      <li><span>{{ tr('telegram_verify_code_label') }}</span><span class="qty">{{ current_user.telegram_verify_code }}</span></li>
    </ul>
    <a href="{{ verify_link }}" target="_blank" rel="noopener" class="btn" style="display:inline-block; text-decoration:none; margin-top:10px;">{{ tr('telegram_verify_open_bot_btn') }} →</a>
    {% endif %}
    {% endif %}
  {% endif %}
</div>
{% endif %}

{% if current_user.is_admin %}
<div class="panel" id="bot-setup-panel" style="max-width:480px;">
  <h2>{{ tr('admin_telegram_setup_title') }}</h2>
  <p class="lede">{{ tr('admin_telegram_setup_lede') }}</p>
  <form method="post" action="{{ url_for('admin_telegram_setup') }}">
    <button type="submit">{{ tr('admin_telegram_setup_btn') }}</button>
  </form>
</div>

<div class="panel" id="backup-panel" style="max-width:480px;">
  <h2>{{ tr('admin_backup_title') }}</h2>
  <p class="lede">{{ tr('admin_backup_lede') }}</p>
  <button type="button" id="backupDownloadBtn" class="btn" style="display:inline-block;">⬇️ {{ tr('admin_backup_btn') }}</button>
  <p id="backupDownloadError" style="display:none; color:var(--red-ink); font-size:12px; margin-top:8px;"></p>
  <script>
  (function () {
    var btn = document.getElementById('backupDownloadBtn');
    var errBox = document.getElementById('backupDownloadError');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var originalText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '{{ tr("please_wait") }}';
      if (errBox) errBox.style.display = 'none';
      fetch("{{ url_for('admin_export_backup') }}", { cache: 'no-store', credentials: 'same-origin' })
        .then(function (res) {
          if (!res.ok) { throw new Error('HTTP ' + res.status); }
          return res.blob();
        })
        .then(function (blob) {
          var stamp = new Date().toISOString().replace(/[:.]/g, '-');
          var url = window.URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = 'gnid_bank_backup_' + stamp + '.json';
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(function () { window.URL.revokeObjectURL(url); }, 2000);
        })
        .catch(function (err) {
          if (errBox) { errBox.textContent = '⚠️ ' + err; errBox.style.display = 'block'; }
        })
        .finally(function () {
          btn.disabled = false;
          btn.textContent = originalText;
        });
    });
  })();
  </script>
</div>
{% endif %}
"""

GUIDE_HTML = """
<div class="panel">
  <h2>{{ tr('guide_title') }}</h2>
  <p class="lede">{{ tr('guide_lede') }}</p>

  <details class="activity-section" open>
    <summary>{{ tr('guide_section_about_title') }}</summary>
    <div class="activity-body"><p style="margin:0; color:var(--ink);">{{ tr('guide_section_about_body') }}</p></div>
  </details>
  <details class="activity-section">
    <summary>{{ tr('guide_section_account_title') }}</summary>
    <div class="activity-body"><p style="margin:0; color:var(--ink);">{{ tr('guide_section_account_body') }}</p></div>
  </details>
  <details class="activity-section">
    <summary>{{ tr('guide_section_deposit_title') }}</summary>
    <div class="activity-body"><p style="margin:0; color:var(--ink);">{{ tr('guide_section_deposit_body') }}</p></div>
  </details>
  <details class="activity-section">
    <summary>{{ tr('guide_section_market_title') }}</summary>
    <div class="activity-body"><p style="margin:0; color:var(--ink);">{{ tr('guide_section_market_body') }}</p></div>
  </details>
  <details class="activity-section">
    <summary>{{ tr('guide_section_invest_title') }}</summary>
    <div class="activity-body"><p style="margin:0; color:var(--ink);">{{ tr('guide_section_invest_body') }}</p></div>
  </details>
  <details class="activity-section">
    <summary>{{ tr('guide_section_loans_title') }}</summary>
    <div class="activity-body"><p style="margin:0; color:var(--ink);">{{ tr('guide_section_loans_body') }}</p></div>
  </details>
  <details class="activity-section">
    <summary>{{ tr('guide_section_withdraw_title') }}</summary>
    <div class="activity-body"><p style="margin:0; color:var(--ink);">{{ tr('guide_section_withdraw_body') }}</p></div>
  </details>
  <details class="activity-section">
    <summary>{{ tr('guide_section_settings_title') }}</summary>
    <div class="activity-body"><p style="margin:0; color:var(--ink);">{{ tr('guide_section_settings_body') }}</p></div>
  </details>
  <details class="activity-section">
    <summary>{{ tr('guide_section_frozen_title') }}</summary>
    <div class="activity-body"><p style="margin:0; color:var(--ink);">{{ tr('guide_section_frozen_body') }}</p></div>
  </details>
</div>

<div class="panel" style="max-width:480px;">
  <h2>{{ tr('contact_support_title') }}</h2>
  <p class="lede">{{ tr('contact_support_lede') }}</p>
  <a href="https://t.me/GNIDBANK" target="_blank" rel="noopener" class="btn" style="display:inline-block; text-decoration:none;">📱 {{ tr('contact_support_btn') }}</a>
</div>
"""

WITHDRAW_HTML = """
<div class="panel" style="max-width:520px;">
  <h2>{{ tr('withdraw_title') }}</h2>
  <p class="lede">{{ tr('withdraw_lede') }}</p>
  <form method="post">
    <div>
      <label>{{ tr('account_link_label') }}</label>
      <input name="account_link" placeholder="https://diplomacia.com.tr/profile/player/1348" required>
      <p style="font-size:11px; color:var(--ink-dim); margin-top:4px;">{{ tr('account_link_hint') }}</p>
    </div>
    <div><label>{{ tr('withdraw_account_name_label') }}</label><input name="account_name"></div>
    <div><label>{{ tr('withdraw_amount_label') }}</label><input name="amount" type="text" inputmode="decimal" class="money-input" required></div>
    <button type="submit">{{ tr('request_withdraw_btn') }}</button>
  </form>
</div>

<div class="panel">
  <h2>{{ tr('my_withdrawals') }}</h2>
  {% if withdrawals %}
  <table>
    <thead><tr><th>{{ tr('amount') }}</th><th>{{ tr('withdraw_account_name_label') }}</th><th>{{ tr('link_col') }}</th><th>{{ tr('date_col') }}</th><th>{{ tr('status_col') }}</th><th></th></tr></thead>
    <tbody>
    {% for w in withdrawals %}
      <tr>
        <td data-label="{{ tr('amount') }}">{{ w.amount|money }}</td>
        <td data-label="{{ tr('withdraw_account_name_label') }}">{{ w.account_name or "—" }}</td>
        <td data-label="{{ tr('link_col') }}"><a href="{{ w.account_link }}" target="_blank" rel="noopener" style="color:var(--gold); white-space:nowrap;">🔗 {{ tr('view_link_word') }}</a></td>
        <td data-label="{{ tr('date_col') }}">{{ w.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="{{ tr('status_col') }}">
          <span class="{{ 'side-buy' if w.status == 'done' else ('side-sell' if w.status in ['rejected', 'cancelled'] else '') }}">
            {{ tr('status_done') if w.status == 'done' else (tr('status_rejected') if w.status == 'rejected' else (tr('status_cancelled') if w.status == 'cancelled' else tr('status_pending'))) }}
          </span>
        </td>
        <td data-label="">
          {% if w.status == 'pending' %}
          <form method="post" action="{{ url_for('cancel_withdraw', request_id=w.id) }}"
                class="confirm-form" data-confirm="{{ tr('confirm_cancel_withdraw') }}">
            <button type="submit" class="danger" style="padding:5px 10px; font-size:12px;">{{ tr('cancel_withdraw_btn') }}</button>
          </form>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_withdrawals_yet') }}</div>{% endif %}
</div>
"""

ADMIN_INVESTMENTS_HTML = """
{% if current_user.is_admin or current_user.is_mod %}
<div class="panel" style="max-width:480px;">
  <h2>{{ tr('admin_add_investment_title') }}</h2>
  <p class="lede">{{ tr('admin_add_investment_lede') }}</p>
  <form method="post">
    <div><label>{{ tr('target_account_id') }}</label><input name="account_id" required></div>
    <div><label>{{ tr('invest_amount_label') }}</label><input name="amount" type="text" inputmode="decimal" class="money-input" required></div>
    <div><label>{{ tr('investment_rate') }} (%)</label><input name="rate" type="number" step="0.01" value="{{ default_rate }}" required></div>
    <div><label>{{ tr('days_passed_label') }}</label><input name="days_passed" type="number" min="0" value="0" required></div>
    <button type="submit">{{ tr('add_investment_btn') }}</button>
  </form>
</div>
{% endif %}

<div class="panel">
  <h2>{{ tr('all_investments_title') }}</h2>
  {% if investments %}
  <table>
    <thead><tr><th>{{ tr('id_label') }}</th><th>{{ tr('username') }}</th><th>{{ tr('telegram_label') }}</th><th>{{ tr('invested_col') }}</th><th>{{ tr('expected_payout_col') }}</th><th>{{ tr('matures_col') }}</th><th>{{ tr('status_col') }}</th><th></th></tr></thead>
    <tbody>
    {% for inv in investments %}
      {% set can_manage = current_user.is_admin or (current_user.is_mod and inv.is_manual and inv.creator_role == 'mod') %}
      <tr>
        <td data-label="{{ tr('id_label') }}">#{{ inv.user.account_id }}</td>
        <td data-label="{{ tr('username') }}">{{ inv.user.username }}{{ vbadge(inv.user)|safe }}</td>
        <td data-label="{{ tr('telegram_label') }}">{{ inv.user.telegram_username|tglink(inv.user.telegram_has_username, inv.user.telegram_chat_id)|safe }}</td>
        <td data-label="{{ tr('invested_col') }}">{{ inv.amount|money }}</td>
        <td data-label="{{ tr('expected_payout_col') }}">{{ inv.payout|money }}</td>
        <td data-label="{{ tr('matures_col') }}">{{ inv.matures_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="{{ tr('status_col') }}">
          <span class="{{ 'side-buy' if inv.status == 'paid' else 'side-sell' }}">{{ tr('status_paid') if inv.status == 'paid' else tr('status_active') }}</span>
        </td>
        <td data-label="" style="display:flex; gap:6px; flex-wrap:wrap;">
          {% if can_manage %}
          {% if inv.is_manual %}
          <button type="button" class="edit-toggle" data-target="edit-inv-{{ inv.id }}" style="padding:6px 12px; font-size:12px;">{{ tr('edit_btn') }}</button>
          {% endif %}
          <form method="post" action="{{ url_for('admin_investment_delete', investment_id=inv.id) }}"
                class="confirm-form" data-confirm="{{ tr('confirm_delete_investment') }}">
            <button type="submit" class="danger" style="padding:6px 12px; font-size:12px;">{{ tr('delete_investment_btn') }}</button>
          </form>
          {% else %}—{% endif %}
        </td>
      </tr>
      {% if inv.is_manual and can_manage %}
      <tr id="edit-inv-{{ inv.id }}" class="edit-row" style="display:none;">
        <td colspan="8">
          <form method="post" action="{{ url_for('admin_investment_edit', investment_id=inv.id) }}" class="inline" style="flex-wrap:wrap; gap:8px;">
            <div><label style="margin:0;">{{ tr('invest_amount_label') }}</label><input name="amount" type="text" inputmode="decimal" class="money-input" value="{{ inv.amount }}" required style="width:130px;"></div>
            <div><label style="margin:0;">{{ tr('investment_rate') }} (%)</label><input name="rate" type="number" step="0.01" value="{{ inv.rate_percent }}" required style="width:90px;"></div>
            <div><label style="margin:0;">{{ tr('days_passed_label') }}</label><input name="days_passed" type="number" min="0" value="{{ ((now - inv.created_at).total_seconds() / 86400) | int }}" required style="width:90px;"></div>
            <button type="submit">{{ tr('save_btn') }}</button>
          </form>
        </td>
      </tr>
      {% endif %}
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_investments_at_all') }}</div>{% endif %}
</div>
<script>
document.querySelectorAll('.edit-toggle').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var row = document.getElementById(btn.dataset.target);
    if (row) { row.style.display = row.style.display === 'none' ? 'table-row' : 'none'; }
  });
});
</script>
"""

ADMIN_WITHDRAWALS_HTML = """
<div class="panel">
  <h2>{{ tr('admin_withdrawals_title') }}</h2>
  <p class="lede">{{ tr('admin_withdrawals_lede') }}</p>
  {% if withdrawals %}
  <table>
    <thead><tr><th>{{ tr('id_label') }}</th><th>{{ tr('username') }}</th><th>{{ tr('telegram_label') }}</th><th>{{ tr('amount') }}</th><th>{{ tr('withdraw_account_name_label') }}</th><th>{{ tr('link_col') }}</th><th>{{ tr('date_col') }}</th><th>{{ tr('status_col') }}</th><th></th></tr></thead>
    <tbody>
    {% for w in withdrawals %}
      <tr>
        <td data-label="{{ tr('id_label') }}">#{{ w.user.account_id }}</td>
        <td data-label="{{ tr('username') }}">{{ w.user.username }}{{ vbadge(w.user)|safe }}</td>
        <td data-label="{{ tr('telegram_label') }}">{{ w.user.telegram_username|tglink(w.user.telegram_has_username, w.user.telegram_chat_id)|safe }}</td>
        <td data-label="{{ tr('amount') }}">{{ w.amount|money }}</td>
        <td data-label="{{ tr('withdraw_account_name_label') }}">{{ w.account_name or "—" }}</td>
        <td data-label="{{ tr('link_col') }}"><a href="{{ w.account_link }}" target="_blank" rel="noopener" style="color:var(--gold); white-space:nowrap;">🔗 {{ tr('view_link_word') }}</a></td>
        <td data-label="{{ tr('date_col') }}">{{ w.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="{{ tr('status_col') }}">
          <span class="{{ 'side-buy' if w.status == 'done' else ('side-sell' if w.status in ['rejected', 'cancelled'] else '') }}">
            {{ tr('status_done') if w.status == 'done' else (tr('status_rejected') if w.status == 'rejected' else (tr('status_cancelled') if w.status == 'cancelled' else tr('status_pending'))) }}
          </span>
        </td>
        <td data-label="">
          {% if w.status == 'pending' %}
          {% if current_user.is_admin %}
          <form method="post" action="{{ url_for('admin_withdraw_auto_send', request_id=w.id) }}" class="inline" style="gap:6px;">
            <button type="submit" style="padding:6px 12px; font-size:12px;">{{ tr('auto_send_btn') }}</button>
          </form>
          {% endif %}
          <form method="post" action="{{ url_for('admin_withdraw_reject', request_id=w.id) }}"
                class="confirm-form" data-confirm="{{ tr('confirm_reject_withdraw') }}" style="margin-top:6px;">
            <button type="submit" class="danger" style="padding:6px 12px; font-size:12px;">{{ tr('reject_btn') }}</button>
          </form>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_pending_withdrawals') }}</div>{% endif %}
</div>
"""

ADMIN_DEPOSITS_HTML = """
<div class="panel" style="max-width:480px;">
  <h2>{{ tr('deposits_and_transfers') }}</h2>
  {% if vault %}
  <p style="margin-bottom:12px;">
    <span class="status-pill {{ 'ok' if vault.healthy else 'bad' }}">
      {{ tr('vault_status_working') if vault.healthy else tr('vault_status_broken') }}
    </span>
  </p>
  <p class="lede">
    {{ tr('vault_last_balance_label') }}: <b style="color:var(--gold);">{{ vault.last_balance|money }}</b>
    {% if vault.updated_at %} — {{ tr('vault_last_update_label') }}: {{ vault.updated_at.strftime("%Y-%m-%d %H:%M") }}{% endif %}
  </p>
  {% else %}
  <p style="margin-bottom:12px;"><span class="status-pill unknown">{{ tr('vault_status_not_set') }}</span></p>
  {% endif %}

  {% if current_user.is_admin %}
  <p class="lede">
    {{ tr('admin_vault_id_range') }} {{ deposit_unit - 1 }} —
    {{ tr('admin_vault_example') }}
  </p>
  <p class="lede">{{ tr('admin_vault_credited_note') }}</p>
  <form method="post" action="{{ url_for('admin_vault_save') }}">
    <div><label>{{ tr('vault_token_label') }}</label><input name="token" value="{{ vault.token if vault else '' }}" placeholder="{{ tr('vault_token_placeholder') }}" required></div>
    <div><label>{{ tr('vault_player_id_label') }}</label><input name="player_id" value="{{ vault.player_id if vault else '' }}" placeholder="1348"></div>
    <div><label>{{ tr('vault_account_name_label') }}</label><input name="account_name" value="{{ vault.account_name if vault else '' }}" placeholder="GNID_BANK_VAULT"></div>
    <div><label>{{ tr('vault_account_url_label') }}</label><input name="account_url" value="{{ vault.account_url if vault else '' }}" placeholder="https://diplomacia.com.tr/..."></div>
    <button type="submit">{{ tr('save_vault_settings_btn') }}</button>
  </form>
  {% else %}
  <p class="lede">{{ tr('mods_view_only_note') }}</p>
  {% endif %}
</div>
"""

NOTIFICATIONS_HTML = """
<div class="panel">
  <h2>{{ tr('notifications_title') }}</h2>
  {% if items %}
  <div style="display:flex; flex-direction:column; gap:12px;">
  {% for n in items %}
    <div class="card" style="padding:14px 16px;">
      <div style="display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin-bottom:6px;">
        <strong style="color:var(--gold); font-size:14px;">{{ n.title }}</strong>
        <span style="font-size:11px; color:var(--ink-dim); white-space:nowrap;">{{ n.created_at.strftime("%Y-%m-%d %H:%M") }}</span>
      </div>
      <div style="font-size:13px; color:var(--ink); white-space:pre-wrap; line-height:1.7;">{{ n.body }}</div>
    </div>
  {% endfor %}
  </div>
  {% else %}<div class="empty">{{ tr('no_notifications_yet') }}</div>{% endif %}
</div>
"""

ADMIN_NOTIFICATIONS_HTML = """
<div class="panel" style="max-width:560px;">
  <h2>{{ tr('admin_notifications_title') }}</h2>
  <p class="lede">{{ tr('admin_notifications_lede') }}</p>
  <form method="post">
    <div><label>{{ tr('notification_title_label') }}</label><input name="title" maxlength="150" required></div>
    <div><label>{{ tr('notification_body_label') }}</label><textarea name="body" rows="4" required style="width:100%;"></textarea></div>
    <button type="submit">{{ tr('send_notification_btn') }}</button>
  </form>
</div>

<div class="panel">
  <h2>{{ tr('sent_notifications_title') }}</h2>
  {% if items %}
  <table>
    <thead><tr><th>{{ tr('notification_title_label') }}</th><th>{{ tr('date_col') }}</th><th></th></tr></thead>
    <tbody>
    {% for n in items %}
      <tr>
        <td data-label="{{ tr('notification_title_label') }}">{{ n.title }}</td>
        <td data-label="{{ tr('date_col') }}">{{ n.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="">
          <form method="post" action="{{ url_for('admin_notification_delete', notification_id=n.id) }}" class="confirm-form" data-confirm="{{ tr('confirm_delete_notification') }}">
            <button type="submit" class="danger" style="padding:6px 12px; font-size:12px;">{{ tr('delete_btn') }}</button>
          </form>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_notifications_yet') }}</div>{% endif %}
</div>
"""

ADMIN_DIVIDENDS_HTML = """
<div class="panel">
  <h2>{{ tr('admin_dividends_title') }}</h2>
  <p class="lede">{{ tr('admin_dividends_lede') }}</p>
  <p style="margin-top:10px; font-size:13px; color:var(--gold); font-weight:700;">{{ tr('dividend_friday_note') }}</p>
</div>

{% for info in stocks_info %}
<div class="panel">
  <h2>{{ info.stock.symbol }} {{ info.stock.name }}</h2>
  <div class="stat-grid" style="margin-bottom:12px;">
    <div class="stat-card"><div class="stat-label">{{ tr('dividend_pct_field') }}</div><div class="stat-value">{{ info.stock.dividend_pct or 0 }}%</div></div>
    <div class="stat-card"><div class="stat-label">{{ tr('top5_total_shares_label') }}</div><div class="stat-value">{{ info.top5_total|money }}</div></div>
  </div>
  {% if info.recent_payouts %}
  <div style="margin-bottom:16px;">
    <div style="font-size:11px; color:var(--gold); letter-spacing:1px; font-weight:700; margin-bottom:8px; text-transform:uppercase;">{{ tr('weekly_profit_trend_title') }}</div>
    <div style="display:flex; gap:8px; overflow-x:auto; padding-bottom:4px;">
    {% for p in info.recent_payouts|reverse %}
      <div style="background:var(--panel-raised); border:1px solid var(--line); border-radius:8px; padding:8px 12px; flex-shrink:0; min-width:100px; text-align:center;">
        <div style="font-size:10px; color:var(--ink-dim); margin-bottom:4px;">{{ p.created_at.strftime("%m-%d") }}</div>
        <div style="font-family:'IBM Plex Mono',monospace; font-weight:700; color:var(--gold); font-size:14px;">{{ p.net_profit|money }}</div>
      </div>
    {% endfor %}
    </div>
  </div>
  {% endif %}
  {% if info.top5 %}
  <table style="margin-bottom:14px;">
    <thead><tr><th>{{ tr('username') }}</th><th>{{ tr('quantity') }}</th><th>{{ tr('dividend_share_pct_col') }}</th></tr></thead>
    <tbody>
    {% for h in info.top5 %}
      <tr>
        <td data-label="{{ tr('username') }}">{{ h.user.username }}{{ vbadge(h.user)|safe }}</td>
        <td data-label="{{ tr('quantity') }}">{{ h.quantity|money }}</td>
        <td data-label="{{ tr('dividend_share_pct_col') }}">{{ "%.2f"|format(h.quantity / info.shares_outstanding * 100 if info.shares_outstanding else 0) }}%</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% if info.stock.dividend_pct and info.stock.dividend_pct > 0 %}
  <form method="post" action="{{ url_for('admin_dividend_distribute', stock_id=info.stock.id) }}" class="confirm-form" data-confirm="{{ tr('confirm_distribute_dividend') }}">
    <div><label>{{ tr('net_profit_label') }}</label><input name="net_profit" type="text" inputmode="decimal" class="money-input" required></div>
    <button type="submit">{{ tr('distribute_btn') }}</button>
  </form>
  {% else %}
  <div class="empty">{{ tr('dividend_disabled_hint') }}</div>
  {% endif %}
  {% else %}
  <div class="empty">{{ tr('no_shareholders_yet') }}</div>
  {% endif %}
</div>
{% endfor %}

<details class="activity-section">
  <summary>{{ tr('dividend_history_title') }} <span class="count-badge">{{ recent_payouts|length }}</span></summary>
  <div class="activity-body">
    {% if recent_payouts %}
    <table>
      <thead><tr><th>{{ tr('company_name_label') }}</th><th>{{ tr('net_profit_label') }}</th><th>{{ tr('dividend_pct_field') }}</th><th>{{ tr('total_fund_label') }}</th><th>{{ tr('recipients_label') }}</th><th>{{ tr('date_col') }}</th></tr></thead>
      <tbody>
      {% for p in recent_payouts %}
        <tr>
          <td data-label="{{ tr('company_name_label') }}">{{ p.stock.symbol }} {{ p.stock.name }}</td>
          <td data-label="{{ tr('net_profit_label') }}">{{ p.net_profit|money }}</td>
          <td data-label="{{ tr('dividend_pct_field') }}">{{ p.dividend_pct }}%</td>
          <td data-label="{{ tr('total_fund_label') }}">{{ p.total_fund|money }}</td>
          <td data-label="{{ tr('recipients_label') }}">{{ p.recipients_count }}</td>
          <td data-label="{{ tr('date_col') }}">{{ p.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<div class="empty">{{ tr('no_dividend_history_yet') }}</div>{% endif %}
  </div>
</details>
"""

ADMIN_COMPANIES_HTML = """
<div class="panel">
  <h2>{{ tr('admin_companies_title') }}</h2>
  <p class="lede">{{ tr('admin_companies_lede') }}</p>
  {% if requests_list %}
  <table>
    <thead><tr><th>{{ tr('username') }}</th><th>{{ tr('company_name_label') }}</th><th>{{ tr('company_level_label') }}</th><th>{{ tr('company_capital_label') }}</th><th>{{ tr('company_daily_production_label') }}</th><th>{{ tr('factory_link_label') }}</th><th>{{ tr('valuation_col') }}</th><th>{{ tr('status_col') }}</th><th></th></tr></thead>
    <tbody>
    {% for r in requests_list %}
      <tr>
        <td data-label="{{ tr('username') }}">{{ r.user.username }}{{ vbadge(r.user)|safe }}</td>
        <td data-label="{{ tr('company_name_label') }}">{{ r.symbol }} {{ r.company_name }}</td>
        <td data-label="{{ tr('company_level_label') }}">{{ r.level }}</td>
        <td data-label="{{ tr('company_capital_label') }}">{{ r.capital|money }}</td>
        <td data-label="{{ tr('company_daily_production_label') }}">{{ r.daily_production|money }}</td>
        <td data-label="{{ tr('factory_link_label') }}"><a href="{{ r.factory_link }}" target="_blank" rel="noopener" style="color:var(--gold); word-break:break-all;">{{ tr('view_link_word') }}</a></td>
        <td data-label="{{ tr('valuation_col') }}">{{ r.computed_valuation|money if r.computed_valuation else "—" }}</td>
        <td data-label="{{ tr('status_col') }}">
          <span class="{{ 'side-buy' if r.status == 'approved' else ('side-sell' if r.status == 'rejected' else '') }}">
            {{ tr('status_approved') if r.status == 'approved' else (tr('status_rejected') if r.status == 'rejected' else tr('status_pending')) }}
          </span>
        </td>
        <td data-label="">
          {% if r.status == 'pending' %}
          <form method="post" action="{{ url_for('admin_company_approve', request_id=r.id) }}" class="inline" style="gap:6px;">
            <button type="submit" style="padding:6px 12px; font-size:12px;">{{ tr('approve_btn') }}</button>
          </form>
          <form method="post" action="{{ url_for('admin_company_reject', request_id=r.id) }}" class="inline" style="gap:6px; margin-top:6px;">
            <input type="text" name="reason" placeholder="{{ tr('reject_reason_placeholder') }}" style="width:130px; font-size:12px;">
            <button type="submit" class="danger" style="padding:6px 12px; font-size:12px;">{{ tr('reject_btn') }}</button>
          </form>
          {% else %}—{% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_company_requests_yet') }}</div>{% endif %}
</div>
"""

ADMIN_CURRENCIES_HTML = """
<div class="panel">
  <h2>{{ tr('admin_currencies_title') }}</h2>
  <p class="lede">{{ tr('admin_currencies_lede') }}</p>
  {% set pending_list = requests_list|selectattr('status', 'equalto', 'pending')|list %}
  {% set handled_list = requests_list|rejectattr('status', 'equalto', 'pending')|list %}
  <h3 style="margin-top:0; border-top:none; padding-top:0;">{{ tr('admin_loans_pending_title') }}{% if pending_list %} ({{ pending_list|length }}){% endif %}</h3>
  {% if pending_list %}
  <table class="stacked-always">
    <thead><tr><th>{{ tr('username') }}</th><th>{{ tr('currency_name_label') }}</th><th>{{ tr('currency_report_col') }}</th><th>{{ tr('date_col') }}</th><th></th></tr></thead>
    <tbody>
    {% for r in pending_list %}
      <tr>
        <td data-label="{{ tr('username') }}">{{ r.user.username }}{{ vbadge(r.user)|safe }}</td>
        <td data-label="{{ tr('currency_name_label') }}">{{ r.symbol }} {{ r.currency_name }}</td>
        <td data-label="{{ tr('currency_report_col') }}" style="max-width:320px; white-space:normal;">{{ r.report_text }}</td>
        <td data-label="{{ tr('date_col') }}">{{ r.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="">
          <form method="post" action="{{ url_for('admin_currency_approve', request_id=r.id) }}" class="inline" style="gap:6px; flex-wrap:wrap;">
            <input type="text" name="unit_price" placeholder="{{ tr('currency_initial_price_label') }}" inputmode="decimal" required style="width:120px; font-size:12px;">
            <input type="number" name="total_supply" placeholder="{{ tr('currency_total_supply_label') }}" min="1" required style="width:120px; font-size:12px;">
            <button type="submit" class="buy" style="padding:6px 12px; font-size:12px;">{{ tr('approve_btn') }}</button>
          </form>
          <form method="post" action="{{ url_for('admin_currency_reject', request_id=r.id) }}" class="inline" style="gap:6px; margin-top:6px;">
            <input type="text" name="reason" placeholder="{{ tr('reject_reason_placeholder') }}" style="width:130px; font-size:12px;">
            <button type="submit" class="danger" style="padding:6px 12px; font-size:12px;">{{ tr('reject_btn') }}</button>
          </form>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_pending_loans') }}</div>{% endif %}

  <h3 style="margin-top:26px;">{{ tr('admin_currencies_title') }}</h3>
  {% if handled_list %}
  <table class="stacked-always">
    <thead><tr><th>{{ tr('username') }}</th><th>{{ tr('currency_name_label') }}</th><th>{{ tr('date_col') }}</th><th>{{ tr('status_col') }}</th></tr></thead>
    <tbody>
    {% for r in handled_list %}
      <tr>
        <td data-label="{{ tr('username') }}">{{ r.user.username }}{{ vbadge(r.user)|safe }}</td>
        <td data-label="{{ tr('currency_name_label') }}">{{ r.symbol }} {{ r.currency_name }}</td>
        <td data-label="{{ tr('date_col') }}">{{ r.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
        <td data-label="{{ tr('status_col') }}">
          <span class="{{ 'side-buy' if r.status == 'approved' else 'side-sell' }}">
            {{ tr('status_approved') if r.status == 'approved' else tr('status_rejected') }}
          </span>
          {% if r.status == 'rejected' and r.reject_reason %}<div style="font-size:11px; color:var(--ink-dim); margin-top:4px;">{{ r.reject_reason }}</div>{% endif %}
          {% if r.status == 'approved' and r.stock %}<div style="margin-top:4px;"><a href="{{ url_for('company_profile', stock_id=r.stock_id) }}" style="color:var(--gold); font-size:12px;">{{ tr('view_currency_btn') }} →</a></div>{% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_rejected_loans') }}</div>{% endif %}
</div>

<div class="panel">
  <h2>{{ tr('currencies_section_title') }}</h2>
  {% set live_currencies = requests_list|selectattr('status', 'equalto', 'approved')|selectattr('stock')|map(attribute='stock')|list %}
  {% if live_currencies %}
  <table class="stacked-always">
    <thead><tr><th>{{ tr('currency_name_label') }}</th><th>{{ tr('currency_owner_label') }}</th><th>{{ tr('status_col') }}</th><th>{{ tr('currency_revenue_label') }}</th><th></th></tr></thead>
    <tbody>
    {% for s in live_currencies %}
      <tr>
        <td data-label="{{ tr('currency_name_label') }}">{{ s.symbol }} {{ s.name }}</td>
        <td data-label="Owner">{{ s.owner_name }} (#{{ s.owner_account_id }})</td>
        <td data-label="{{ tr('status_col') }}">{% if s.suspended %}<span style="color:var(--red);">{{ tr('suspended_badge') }}</span>{% else %}<span class="side-buy">✅</span>{% endif %}</td>
        <td data-label="{{ tr('currency_revenue_label') }}">
          <form method="post" action="{{ url_for('admin_currency_distribute', stock_id=s.id) }}" class="inline confirm-form" data-confirm="{{ tr('confirm_distribute_revenue') }}" style="gap:6px;">
            <input type="text" name="revenue" placeholder="{{ tr('currency_revenue_label') }}" inputmode="decimal" required style="width:120px; font-size:12px;">
            <button type="submit" style="padding:6px 12px; font-size:12px;">{{ tr('distribute_revenue_btn') }}</button>
          </form>
        </td>
        <td data-label="">
          {% if s.suspended %}
          <form method="post" action="{{ url_for('admin_stock_resume', stock_id=s.id) }}"><button type="submit" style="padding:6px 12px; font-size:12px;">{{ tr('resume_btn') }}</button></form>
          {% else %}
          <form method="post" action="{{ url_for('admin_stock_suspend', stock_id=s.id) }}"><button type="submit" class="danger" style="padding:6px 12px; font-size:12px;">{{ tr('suspend_btn') }}</button></form>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_live_currencies') }}</div>{% endif %}
</div>
"""

ADMIN_STOCKS_HTML = """
{% if current_user.is_admin or current_user.is_mod %}
<div class="panel" style="max-width:480px;">
  <h2>{{ tr('manage_stocks_title') }}</h2>
  <p class="lede">{{ tr('manage_stocks_lede') }}</p>
  <form method="post">
    <div>
      <label>{{ tr('stock_icon_label') }}</label>
      <div class="icon-picker">
        {% for icon in STOCK_ICONS %}
        <label class="icon-choice">
          <input type="radio" name="symbol" value="{{ icon }}" {% if loop.first %}checked{% endif %} required>
          <span>{{ icon }}</span>
        </label>
        {% endfor %}
      </div>
    </div>
    <div><label>{{ tr('stock_name') }}</label><input name="name" required></div>
    <div><label>{{ tr('company_description') }}</label><textarea name="description" rows="2"></textarea></div>
    <div><label>{{ tr('company_sector') }}</label><input name="sector"></div>
    <div><label>{{ tr('company_owner') }}</label><input name="owner_name"></div>
    <div><label>{{ tr('company_owner_account_id') }}</label><input name="owner_account_id" placeholder="#"></div>
    <div><label>{{ tr('sale_price') }}</label><input name="price" type="text" inputmode="decimal" class="money-input" required></div>
    <div><label>{{ tr('total_shares_label') }}</label><input name="total_shares" type="number" min="1" required></div>
    <div><label>{{ tr('owner_pct_field') }}</label><input name="owner_pct" type="number" step="0.01" min="0" max="100" value="0"></div>
    <div><label>{{ tr('gnid_pct_field') }}</label><input name="gnid_pct" type="number" step="0.01" min="0" max="100" value="0"></div>
    <button type="submit">{{ tr('save_btn') }}</button>
  </form>
</div>
{% endif %}

<div class="panel">
  <h2>{{ tr('current_stocks') }}</h2>
  {% if not current_user.is_admin %}<p class="lede">{{ tr('mods_can_edit_note') }}</p>{% endif %}
  {% if stocks %}
  <table>
    <thead><tr><th>{{ tr('symbol') }}</th><th>{{ tr('name_col') }}</th><th>{{ tr('price') }}</th><th>{{ tr('available') }}</th><th></th></tr></thead>
    <tbody>
    {% for s in stocks %}
      {% set can_edit = current_user.is_admin or (current_user.is_mod and s.creator_role != 'admin') %}
      <tr>
        <td data-label="{{ tr('symbol') }}" style="font-size:20px;">{{ s.symbol }}</td>
        <td data-label="{{ tr('name_col') }}"><a href="{{ url_for('company_profile', stock_id=s.id) }}" style="color:var(--gold);">{{ s.name }}</a></td>
        <td data-label="{{ tr('price') }}">{{ s.admin_price|money }}</td>
        <td data-label="{{ tr('available') }}">{{ s.admin_supply|money }}</td>
        <td data-label="">
          {% if can_edit %}
          <button type="button" class="edit-toggle" data-target="edit-stock-{{ s.id }}" style="padding:5px 10px; font-size:12px;">{{ tr('edit_btn') }}</button>
          {% else %}
          <span class="status-pill unknown" style="font-size:11px;">🔒 {{ tr('created_by_admin_locked') }}</span>
          {% endif %}
        </td>
      </tr>
      {% if can_edit %}
      <tr id="edit-stock-{{ s.id }}" class="edit-row" style="display:none;">
        <td colspan="5">
          <form method="post" action="{{ url_for('admin_stock_edit', stock_id=s.id) }}" class="inline" style="flex-wrap:wrap; gap:8px;">
            <div>
              <label>{{ tr('stock_icon_label') }}</label>
              <div class="icon-picker">
                {% for icon in STOCK_ICONS %}
                <label class="icon-choice">
                  <input type="radio" name="symbol" value="{{ icon }}" {% if icon == s.symbol %}checked{% endif %}>
                  <span>{{ icon }}</span>
                </label>
                {% endfor %}
              </div>
            </div>
            <div><label>{{ tr('stock_name') }}</label><input name="name" value="{{ s.name }}" required></div>
            <div><label>{{ tr('company_description') }}</label><textarea name="description" rows="2">{{ s.description or '' }}</textarea></div>
            <div><label>{{ tr('company_sector') }}</label><input name="sector" value="{{ s.sector or '' }}"></div>
            <div><label>{{ tr('company_owner') }}</label><input name="owner_name" value="{{ s.owner_name or '' }}"></div>
            <div><label>{{ tr('company_owner_account_id') }}</label><input name="owner_account_id" value="{{ s.owner_account_id or '' }}" placeholder="#"></div>
            <div><label>{{ tr('sale_price') }}</label><input name="price" type="text" inputmode="decimal" class="money-input" value="{{ s.admin_price }}" required></div>
            <div><label>{{ tr('quantity') }}</label><input name="supply" type="number" value="{{ s.admin_supply }}" required></div>
            <div><label>{{ tr('total_shares_label') }}</label><input name="total_shares" type="number" value="{{ s.total_shares or '' }}" placeholder="{{ tr('total_shares_hint') }}"></div>
            <div><label>{{ tr('owner_shares_field') }}</label><input name="owner_shares" type="number" min="0" value="{{ s.owner_shares or 0 }}"></div>
            <div><label>{{ tr('gnid_shares_field') }}</label><input name="gnid_shares" type="number" min="0" value="{{ s.gnid_shares or 0 }}"></div>
            <div><label>{{ tr('dividend_pct_field') }}</label><input name="dividend_pct" type="text" inputmode="decimal" value="{{ s.dividend_pct or 0 }}" placeholder="{{ tr('dividend_pct_hint') }}"></div>
            <button type="submit">{{ tr('save_changes_btn') }}</button>
          </form>
          {% if current_user.is_admin %}
          <form method="post" action="{{ url_for('admin_stock_delete', stock_id=s.id) }}"
                class="confirm-form" data-confirm="{{ tr('confirm_delete_stock') }}" style="margin-top:8px; flex-wrap:wrap; gap:6px;">
            <input type="password" name="confirm_password" placeholder="{{ tr('confirm_password_to_delete') }}" required style="width:160px; font-size:12px;">
            <button type="submit" class="danger" style="padding:6px 12px; font-size:12px;">{{ tr('delete_btn') }}</button>
          </form>
          <form method="post" action="{{ url_for('admin_stock_delete_refund', stock_id=s.id) }}"
                class="confirm-form" data-confirm="{{ tr('confirm_delete_refund_stock') }}" style="margin-top:8px; flex-wrap:wrap; gap:6px;">
            <input type="password" name="confirm_password" placeholder="{{ tr('confirm_password_to_delete') }}" required style="width:160px; font-size:12px;">
            <button type="submit" class="danger" style="padding:6px 12px; font-size:12px;">💸 {{ tr('delete_refund_btn') }}</button>
          </form>
          {% endif %}
        </td>
      </tr>
      {% endif %}
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_stocks_added') }}</div>{% endif %}
</div>
<script>
document.querySelectorAll('.edit-toggle').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var row = document.getElementById(btn.dataset.target);
    if (row) { row.style.display = row.style.display === 'none' ? 'table-row' : 'none'; }
  });
});
</script>
"""

ADMIN_USERS_HTML = """
<div class="panel">
  <h2>{{ tr('manage_users_title') }}</h2>
  <p class="lede">{{ tr('manage_users_lede') }}{% if not current_user.is_admin %} {{ tr('mods_view_only_note') }}{% endif %}</p>
  {% if users %}
  <input type="text" id="userSearchInput" placeholder="{{ tr('search_users_placeholder') }}"
         style="width:100%; padding:10px 14px; margin-bottom:14px; border-radius:8px; border:1px solid var(--line); background:var(--panel-raised); color:var(--ink); font-size:14px; box-sizing:border-box;">
  <div id="noSearchResults" class="empty" style="display:none;">{{ tr('no_search_results') }}</div>
  <table class="stacked-always">
    <thead>
      <tr><th>{{ tr('id_label') }}</th><th>{{ tr('username') }}</th><th>{{ tr('telegram_label') }}</th><th>{{ tr('telegram_verify_title') }}</th><th>{{ tr('balance_col') }}</th><th>{{ tr('is_admin_col') }}</th><th>{{ tr('frozen_col') }}</th>{% if current_user.is_admin %}<th></th>{% endif %}</tr>
    </thead>
    <tbody>
    {% for u in users %}
      <tr class="user-row" data-search="{{ (u.username ~ ' ' ~ u.telegram_username ~ ' ' ~ u.account_id)|lower }}">
        <td data-label="{{ tr('id_label') }}">#{{ u.account_id }}</td>
        <td data-label="{{ tr('username') }}">
          <button type="button" class="user-toggle" data-group="user-extra-{{ u.id }}" aria-label="expand">▸</button>
          {{ u.username }}{{ vbadge(u)|safe }}
        </td>
        <td data-label="{{ tr('telegram_label') }}" class="user-extra" data-group="user-extra-{{ u.id }}" hidden>{{ u.telegram_username|tglink(u.telegram_has_username, u.telegram_chat_id)|safe }}</td>
        <td data-label="{{ tr('telegram_verify_title') }}" class="user-extra" data-group="user-extra-{{ u.id }}" hidden>
          <span class="status-pill {{ 'ok' if u.telegram_verified else 'unknown' }}" style="font-size:11px;">
            {{ tr('telegram_verify_status_verified') if u.telegram_verified else tr('telegram_verify_status_not_verified') }}
          </span>
        </td>
        <td data-label="{{ tr('balance_col') }}" class="user-extra" data-group="user-extra-{{ u.id }}" hidden>{{ u.balance|money }}</td>
        <td data-label="{{ tr('is_admin_col') }}" class="user-extra" data-group="user-extra-{{ u.id }}" hidden>{{ tr('yes_word') if u.is_admin else tr('no_word') }}</td>
        <td data-label="{{ tr('frozen_col') }}" class="user-extra" data-group="user-extra-{{ u.id }}" hidden>
          {% if u.is_frozen %}<span class="status-pill" style="font-size:11px; color:var(--red-ink); border-color:var(--red);">🔒 {{ tr('frozen_word') }}</span>
          {% if current_user.is_admin %}
          <form method="post" action="{{ url_for('admin_unfreeze_user', user_id=u.id) }}" style="display:inline;">
            <button type="submit" style="padding:3px 8px; font-size:11px; margin-inline-start:6px;">{{ tr('unfreeze_btn') }}</button>
          </form>
          {% endif %}
          {% else %}—{% endif %}
        </td>
        {% if current_user.is_admin %}
        <td data-label="" class="user-extra" data-group="user-extra-{{ u.id }}" hidden style="display:flex; gap:6px; flex-wrap:wrap;">
          <button type="button" class="edit-toggle" data-target="edit-user-{{ u.id }}" style="padding:5px 10px; font-size:12px;">{{ tr('edit_btn') }}</button>
          {% if u.id != current_user.id %}
          <form method="post" action="{{ url_for('admin_delete_user', user_id=u.id) }}"
                class="confirm-form" data-confirm="{{ tr('confirm_delete_user') }}">
            <button type="submit" class="danger" style="padding:5px 10px; font-size:12px;">{{ tr('delete_account_btn') }}</button>
          </form>
          {% else %}
          <span style="color:var(--ink-dim); font-size:12px;">{{ tr('your_account_label') }}</span>
          {% endif %}
        </td>
        {% endif %}
      </tr>
      {% if current_user.is_admin %}
      <tr id="edit-user-{{ u.id }}" class="edit-row user-extra" data-group="user-extra-{{ u.id }}" style="display:none;" hidden>
        <td colspan="8">
          <form method="post" action="{{ url_for('admin_adjust_balance', user_id=u.id) }}" class="inline" style="flex-wrap:wrap; gap:8px; margin-bottom:10px;">
            <label style="margin:0;">{{ tr('adjust_balance_btn') }}</label>
            <select name="direction" style="width:110px;">
              <option value="add">{{ tr('add_word') }}</option>
              <option value="subtract">{{ tr('subtract_word') }}</option>
            </select>
            <input name="amount" type="text" inputmode="decimal" class="money-input" placeholder="{{ tr('amount') }}" required style="width:130px;">
            <button type="submit">{{ tr('apply_btn') }}</button>
          </form>
          <form method="post" action="{{ url_for('admin_change_password', user_id=u.id) }}" class="inline" style="flex-wrap:wrap; gap:8px;">
            <label style="margin:0;">{{ tr('change_password_btn') }}</label>
            <input name="password" type="password" placeholder="{{ tr('new_password_placeholder') }}" required style="width:180px;">
            <button type="submit">{{ tr('save_password_btn') }}</button>
          </form>
        </td>
      </tr>
      {% endif %}
    {% endfor %}
    </tbody>
  </table>
  {% else %}<div class="empty">{{ tr('no_users_yet') }}</div>{% endif %}
</div>
<script>
document.querySelectorAll('.edit-toggle').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var row = document.getElementById(btn.dataset.target);
    if (row) {
      var willShow = row.style.display === 'none';
      row.style.display = willShow ? 'table-row' : 'none';
      row.hidden = !willShow;
    }
  });
});

document.querySelectorAll('.user-toggle').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var group = btn.dataset.group;
    var isExpanding = btn.textContent.trim() === '▸';
    btn.textContent = isExpanding ? '▾' : '▸';
    document.querySelectorAll('.user-extra[data-group="' + group + '"]').forEach(function (el) {
      if (el.classList.contains('edit-row')) {
        // لو هيتقفل الصف الأساسي، اقفل صف التعديل معاه لو كان مفتوح
        if (!isExpanding) { el.style.display = 'none'; el.hidden = true; }
        return;
      }
      el.hidden = !isExpanding;
    });
  });
});

(function () {
  var input = document.getElementById('userSearchInput');
  if (!input) return;
  var noResults = document.getElementById('noSearchResults');
  input.addEventListener('input', function () {
    var q = input.value.trim().toLowerCase();
    var visibleCount = 0;
    document.querySelectorAll('tr.user-row').forEach(function (row) {
      var match = !q || row.dataset.search.indexOf(q) !== -1;
      row.style.display = match ? '' : 'none';
      if (match) { visibleCount++; }
      else {
        // اقفل تفاصيل أي صف مخفي بالبحث عشان لو ظهر تاني يبان مطوي
        var group = row.querySelector('.user-toggle') ? row.querySelector('.user-toggle').dataset.group : null;
        if (group) {
          document.querySelectorAll('.user-extra[data-group="' + group + '"]').forEach(function (el) { el.hidden = true; if (el.classList.contains('edit-row')) el.style.display = 'none'; });
          var toggleBtn = row.querySelector('.user-toggle');
          if (toggleBtn) toggleBtn.textContent = '▸';
        }
      }
    });
    if (noResults) { noResults.style.display = visibleCount === 0 ? 'block' : 'none'; }
  });
})();
</script>
"""


# ============================================================
# Auth routes
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        confirm_password = request.form.get("confirm_password", "")
        telegram_username = request.form["telegram_username"].strip().lstrip("@")

        if not telegram_username:
            flash(tr("flash_no_telegram"))
            return redirect(url_for("register"))
        if not is_valid_telegram_username(telegram_username):
            flash(tr("flash_telegram_invalid_format"))
            return redirect(url_for("register"))
        if password != confirm_password:
            flash(tr("flash_passwords_dont_match"))
            return redirect(url_for("register"))
        if len(password) < 6:
            flash(tr("flash_password_too_short"))
            return redirect(url_for("register"))
        if User.query.filter(func.lower(User.username) == username.lower()).first():
            flash(tr("flash_user_exists"))
            return redirect(url_for("register"))

        u = User(username=username, telegram_username=telegram_username,
                  account_id=generate_account_id())
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        login_user(u, remember=True)
        return redirect(url_for("dashboard"))
    return page(REGISTER_HTML)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        now = datetime.utcnow().timestamp()
        fails = _login_failure_buckets.setdefault(ip, [])
        while fails and now - fails[0] > 300:  # نافذة 5 دقايق
            fails.pop(0)
        if len(fails) >= 8:
            flash(tr("flash_too_many_login_attempts"))
            return page(LOGIN_HTML)

        username = request.form["username"].strip()
        password = request.form["password"]
        u = User.query.filter(func.lower(User.username) == username.lower()).first()
        if u and u.check_password(password):
            fails.clear()
            login_user(u, remember=True)
            return redirect(url_for("dashboard"))
        fails.append(now)
        flash(tr("flash_bad_login"))
    return page(LOGIN_HTML)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/system-reset-db/<key>")
def system_reset_db(key):
    """معطّل نهائيًا. كان مسار مؤقت لتصفير الجداول وقت التطوير الأول، لكن سيبه شغال في
    الإنتاج فيه خطورة حقيقية - أي حد يعرف SECRET_KEY يقدر يمسح قاعدة البيانات بالكامل عن
    طريق GET request بسيط. اتقفل خالص هنا؛ لو محتاج تصفير الجداول تاني، اعمله يدوي من الداتابيز
    مباشرة مش عن طريق مسار في الكود."""
    return "غير متاح", 404


# ============================================================
# Dashboard / Transfer
# ============================================================

@app.route("/")
@login_required
def dashboard():
    holdings = Holding.query.filter_by(user_id=current_user.id).all()
    holdings_value = sum(h.quantity * h.stock.price_stats()["current"] for h in holdings)

    active_investments = Investment.query.filter_by(user_id=current_user.id, status="active").all()
    total_invested = sum(i.amount for i in active_investments)
    total_expected_payout = sum(i.payout for i in active_investments)
    next_maturity = min((i.matures_at for i in active_investments), default=None)

    pending_withdrawals_total = sum(
        w.amount for w in WithdrawalRequest.query.filter_by(user_id=current_user.id, status="pending").all()
    )

    greeting_date = datetime.utcnow().strftime("%Y-%m-%d")

    loan_due_soon = LoanRequest.query.filter(
        LoanRequest.user_id == current_user.id,
        LoanRequest.status == "approved",
        LoanRequest.due_date.isnot(None),
        LoanRequest.due_date <= datetime.utcnow() + timedelta(days=1),
    ).order_by(LoanRequest.due_date.asc()).first()

    return page(DASHBOARD_HTML, holdings=holdings, holdings_value=holdings_value, deposit_unit=DEPOSIT_UNIT,
                active_investments_count=len(active_investments), total_invested=total_invested,
                total_expected_payout=total_expected_payout, next_maturity=next_maturity,
                pending_withdrawals_total=pending_withdrawals_total, greeting_date=greeting_date,
                investment_terms=INVESTMENT_TERMS,
                loan_due_soon=loan_due_soon)


@app.route("/deposit")
@login_required
def deposit():
    vault = Vault.query.get(1)
    deposits = (Deposit.query
                .filter_by(user_id=current_user.id, status="confirmed")
                .order_by(Deposit.created_at.desc())
                .all())
    return page(DEPOSIT_HTML, vault=vault, deposits=deposits, deposit_unit=DEPOSIT_UNIT)


# ============================================================
# Stocks: Admin IPO
# ============================================================

@app.route("/admin/stocks", methods=["GET", "POST"])
@login_required
def admin_stocks():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403

    if request.method == "POST":
        # الإضافة (شركة جديدة) متاحة للأدمن والمشرف. التعديل/الحذف ليهم قواعد تانية في الروتس بتاعتهم.
        symbol = request.form["symbol"].strip()
        name = request.form["name"].strip()
        price = float(request.form["price"])
        description = request.form.get("description", "").strip()
        sector = request.form.get("sector", "").strip()
        owner_name = request.form.get("owner_name", "").strip()
        owner_account_id = request.form.get("owner_account_id", "").strip().lstrip("#")
        try:
            total_shares = int(request.form["total_shares"])
        except (ValueError, TypeError, KeyError):
            total_shares = 0
        try:
            owner_pct = float(request.form.get("owner_pct") or 0)
            gnid_pct = float(request.form.get("gnid_pct") or 0)
        except (ValueError, TypeError):
            owner_pct = gnid_pct = 0

        if total_shares <= 0:
            flash(tr("flash_bad_amount"))
            return redirect(url_for("admin_stocks"))
        if owner_pct + gnid_pct > 100:
            flash(tr("flash_ownership_over_100"))
            return redirect(url_for("admin_stocks"))

        owner_shares = round(total_shares * owner_pct / 100)
        gnid_shares = round(total_shares * gnid_pct / 100)
        market_supply = total_shares - owner_shares - gnid_shares

        stock = Stock(symbol=symbol, name=name, admin_price=price, admin_supply=market_supply,
                      description=description, sector=sector, owner_name=owner_name,
                      owner_account_id=owner_account_id,
                      total_shares=total_shares, owner_shares=owner_shares, gnid_shares=gnid_shares,
                      creator_username=current_user.username,
                      creator_role=("admin" if current_user.is_admin else "mod"))
        db.session.add(stock)
        db.session.add(AdminActionLog(admin_username=current_user.username,
                                        actor_role=("admin" if current_user.is_admin else "mod"),
                                        action="stock_add", target_username=f"{symbol} {name}"))
        db.session.commit()
        flash(tr("flash_stock_saved"))

    stocks = Stock.query.all()
    return page(ADMIN_STOCKS_HTML, stocks=stocks)


@app.route("/admin/stocks/<int:stock_id>/edit", methods=["POST"])
@login_required
def admin_stock_edit(stock_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403

    stock = Stock.query.get_or_404(stock_id)

    # المشرف يقدر يعدّل بس الشركات اللي مشرف (أي مشرف) أنشأها - مش اللي عملها الأدمن
    if current_user.is_mod and not current_user.is_admin and stock.creator_role == "admin":
        return tr("not_authorized"), 403

    stock.symbol = request.form.get("symbol", stock.symbol).strip() or stock.symbol
    stock.name = request.form["name"].strip()
    stock.admin_price = float(request.form["price"])
    stock.admin_supply = int(request.form["supply"])  # قيمة مباشرة (set) مش إضافة
    stock.description = request.form.get("description", "").strip()
    stock.sector = request.form.get("sector", "").strip()
    stock.owner_name = request.form.get("owner_name", "").strip()
    stock.owner_account_id = request.form.get("owner_account_id", "").strip().lstrip("#")
    try:
        stock.total_shares = int(request.form.get("total_shares") or 0)
    except (ValueError, TypeError):
        stock.total_shares = 0
    try:
        stock.owner_shares = int(request.form.get("owner_shares") or 0)
    except (ValueError, TypeError):
        stock.owner_shares = 0
    try:
        stock.gnid_shares = int(request.form.get("gnid_shares") or 0)
    except (ValueError, TypeError):
        stock.gnid_shares = 0
    try:
        stock.dividend_pct = max(0.0, min(100.0, float(request.form.get("dividend_pct") or 0)))
    except (ValueError, TypeError):
        stock.dividend_pct = 0
    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="stock_edit", target_username=f"{stock.symbol} {stock.name}"))
    db.session.commit()
    flash(tr("flash_stock_updated"))
    return redirect(url_for("admin_stocks"))


@app.route("/admin/stocks/<int:stock_id>/delete", methods=["POST"])
@login_required
def admin_stock_delete(stock_id):
    if not current_user.is_admin:
        return tr("not_authorized"), 403

    stock = Stock.query.get_or_404(stock_id)

    # تأكيد إضافي: الأدمن لازم يكتب باسورد حسابه هو نفسه قبل ما يقدر يحذف شركة كاملة -
    # عشان حذف شركة إجراء خطير ومش ممكن التراجع عنه (بيمسح كل صفقاتها وحيازاتها)
    confirm_password = request.form.get("confirm_password", "")
    if not current_user.check_password(confirm_password):
        flash(tr("flash_wrong_confirm_password"))
        return redirect(url_for("admin_stocks"))

    # فك أي روابط لسجلات الصفقات قبل حذف السهم - عشان مايحصلش خطأ Foreign Key
    trade_ids = [t.id for t in Trade.query.filter_by(stock_id=stock.id).all()]
    if trade_ids:
        # سجلات دخل الخزينة من عمولات الصفقات دي تفضل موجودة (فلوس حقيقية دخلت الخزينة)،
        # بس بنفك ربطها بالصفقة المحذوفة عشان محدش يحاول يوصلها بسهم مبقاش موجود
        TreasuryEntry.query.filter(TreasuryEntry.trade_id.in_(trade_ids)).update(
            {"trade_id": None}, synchronize_session=False
        )
    Trade.query.filter_by(stock_id=stock.id).delete()
    Order.query.filter_by(stock_id=stock.id).delete()
    Holding.query.filter_by(stock_id=stock.id).delete()
    # توزيعات الأرباح/الإيراد القديمة على السهم/العملة ده لازم تتمسح كمان (وتفاصيل كل
    # مستفيد منها) قبل حذف السهم - عمود stock_id في DividendPayout إجباري (NOT NULL)
    # فمينفعش نسيبه معلّق زي CompanyRequest، لازم يتمسح فعليًا
    old_payout_ids = [p.id for p in DividendPayout.query.filter_by(stock_id=stock.id).all()]
    if old_payout_ids:
        DividendRecipient.query.filter(DividendRecipient.payout_id.in_(old_payout_ids)).delete(synchronize_session=False)
        DividendPayout.query.filter_by(stock_id=stock.id).delete()
    # لو السهم ده كان اتعمل من طلب تسجيل شركة (approved)، بنفك الربط بس مش بنمسح الطلب نفسه -
    # يفضل موجود كسجل تاريخي إن الطلب اتوافق عليه، حتى لو السهم اتحذف بعدين
    CompanyRequest.query.filter_by(stock_id=stock.id).update({"stock_id": None}, synchronize_session=False)
    CurrencyRequest.query.filter_by(stock_id=stock.id).update({"stock_id": None}, synchronize_session=False)
    db.session.add(AdminActionLog(admin_username=current_user.username, actor_role="admin",
                                    action="stock_delete", target_username=f"{stock.symbol} {stock.name}"))
    db.session.delete(stock)
    db.session.commit()
    flash(tr("flash_stock_deleted"))
    return redirect(url_for("admin_stocks"))


@app.route("/admin/stocks/<int:stock_id>/delete-refund", methods=["POST"])
@login_required
def admin_stock_delete_refund(stock_id):
    if not current_user.is_admin:
        return tr("not_authorized"), 403

    stock = Stock.query.get_or_404(stock_id)

    confirm_password = request.form.get("confirm_password", "")
    if not current_user.check_password(confirm_password):
        flash(tr("flash_wrong_confirm_password"))
        return redirect(url_for("admin_stocks"))

    # لكل مستخدم معاه أسهم فعلية، بنحسب متوسط سعر الشراء المرجح من كل صفقاته اللي اشترى بيها
    # السهم ده (IPO أو من السوق)، وبنرجعله فلوسه بالسعر ده × عدد الأسهم اللي معاه دلوقتي.
    # لو مفيش سجل شراء له خالص (زي تخصيص إداري قديم)، بيترجعله بآخر سعر معروف للسهم كبديل عادل.
    holdings = Holding.query.filter_by(stock_id=stock.id).filter(Holding.quantity > 0).all()
    refunded_count = 0
    total_refunded = 0.0
    for h in holdings:
        buy_trades = Trade.query.filter_by(stock_id=stock.id, buyer_id=h.user_id).all()
        total_bought_qty = sum(t.quantity for t in buy_trades)
        if total_bought_qty > 0:
            total_spent = sum(t.quantity * t.price for t in buy_trades)
            avg_price = total_spent / total_bought_qty
        else:
            avg_price = stock.price_stats()["current"]
        refund_amount = avg_price * h.quantity
        h.user.balance += refund_amount
        total_refunded += refund_amount
        refunded_count += 1

    # فك أي روابط لسجلات الصفقات قبل حذف السهم - عشان مايحصلش خطأ Foreign Key
    trade_ids = [t.id for t in Trade.query.filter_by(stock_id=stock.id).all()]
    if trade_ids:
        TreasuryEntry.query.filter(TreasuryEntry.trade_id.in_(trade_ids)).update(
            {"trade_id": None}, synchronize_session=False
        )
    Trade.query.filter_by(stock_id=stock.id).delete()
    Order.query.filter_by(stock_id=stock.id).delete()
    Holding.query.filter_by(stock_id=stock.id).delete()
    old_payout_ids = [p.id for p in DividendPayout.query.filter_by(stock_id=stock.id).all()]
    if old_payout_ids:
        DividendRecipient.query.filter(DividendRecipient.payout_id.in_(old_payout_ids)).delete(synchronize_session=False)
        DividendPayout.query.filter_by(stock_id=stock.id).delete()
    CompanyRequest.query.filter_by(stock_id=stock.id).update({"stock_id": None}, synchronize_session=False)
    CurrencyRequest.query.filter_by(stock_id=stock.id).update({"stock_id": None}, synchronize_session=False)
    db.session.delete(stock)
    db.session.commit()
    flash(f"{tr('flash_stock_deleted_refunded')} ({refunded_count} × {format_money(total_refunded)})")
    return redirect(url_for("admin_stocks"))


@app.route("/admin/vault/save", methods=["POST"])
@login_required
def admin_vault_save():
    if not current_user.is_admin:
        return tr("not_authorized"), 403
    vault = Vault.query.get(1)
    if not vault:
        vault = Vault(id=1, last_balance=0)
        db.session.add(vault)
    vault.token = request.form["token"].strip()
    vault.player_id = request.form.get("player_id", "").strip()
    vault.account_name = request.form.get("account_name", "").strip()
    vault.account_url = request.form.get("account_url", "").strip()
    db.session.commit()
    flash("تم حفظ إعدادات الخزنة")
    return redirect(url_for("admin_deposits"))


@app.route("/admin/users")
@login_required
def admin_users():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    users = User.query.order_by(db.cast(User.account_id, db.Integer).asc()).all()
    return page(ADMIN_USERS_HTML, users=users)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        return tr("not_authorized"), 403
    if user_id == current_user.id:
        flash("مينفعش تحذف حسابك بنفسك")
        return redirect(url_for("admin_users"))

    target = User.query.get_or_404(user_id)

    # فك أي أوامر مفتوحة، وشيل/فُك كل البيانات المرتبطة بالحساب قبل حذفه (عشان نتجنب
    # خطأ ForeignKeyViolation ونحافظ في نفس الوقت على سجل الصفقات (Trade) للأبد للإحصائيات)
    Order.query.filter_by(user_id=target.id).delete()
    Holding.query.filter_by(user_id=target.id).delete()
    Transaction.query.filter(
        (Transaction.sender_id == target.id) | (Transaction.receiver_id == target.id)
    ).delete(synchronize_session=False)
    Deposit.query.filter_by(user_id=target.id).update({"user_id": None})
    LoanRequest.query.filter_by(user_id=target.id).delete()
    Investment.query.filter_by(user_id=target.id).delete()
    WithdrawalRequest.query.filter_by(user_id=target.id).delete()
    # سجلات الصفقات (Trade) بيتفك ربطها بالمستخدم المحذوف بس مبتتمسحش خالص - عشان
    # المخططات والإحصائيات التاريخية للأسهم تفضل صحيحة زي ما هي دايمًا
    Trade.query.filter_by(buyer_id=target.id).update({"buyer_id": None})
    Trade.query.filter_by(seller_id=target.id).update({"seller_id": None})

    username = target.username
    account_id = target.account_id
    db.session.add(AdminActionLog(admin_username=current_user.username, actor_role=("admin" if current_user.is_admin else "mod"), action="user_delete",
                                    target_username=username, target_account_id=account_id))
    db.session.delete(target)
    db.session.commit()
    flash(f"تم حذف حساب {username} نهائيًا")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/unfreeze", methods=["POST"])
@login_required
def admin_unfreeze_user(user_id):
    if not current_user.is_admin:
        return tr("not_authorized"), 403
    target = User.query.get_or_404(user_id)
    target.is_frozen = False
    target.frozen_reason = None
    db.session.add(AdminActionLog(admin_username=current_user.username, actor_role="admin", action="user_unfreeze",
                                    target_username=target.username, target_account_id=target.account_id))
    db.session.commit()
    flash(tr("flash_user_unfrozen"))
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/balance", methods=["POST"])
@login_required
def admin_adjust_balance(user_id):
    if not current_user.is_admin:
        return tr("not_authorized"), 403

    target = User.query.get_or_404(user_id)
    direction = request.form.get("direction", "add")
    try:
        amount = float(request.form["amount"])
    except (ValueError, TypeError):
        amount = 0

    if amount <= 0:
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_users"))

    if direction == "subtract":
        if target.balance < amount:
            flash(tr("flash_insufficient_target"))
            return redirect(url_for("admin_users"))
        target.balance -= amount
        db.session.add(AdminActionLog(admin_username=current_user.username, actor_role=("admin" if current_user.is_admin else "mod"), action="balance_subtract",
                                        target_username=target.username, target_account_id=target.account_id,
                                        amount=amount))
    else:
        target.balance += amount
        db.session.add(AdminActionLog(admin_username=current_user.username, actor_role=("admin" if current_user.is_admin else "mod"), action="balance_add",
                                        target_username=target.username, target_account_id=target.account_id,
                                        amount=amount))

    db.session.commit()
    flash(tr("flash_balance_adjusted"))
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/password", methods=["POST"])
@login_required
def admin_change_password(user_id):
    if not current_user.is_admin:
        return tr("not_authorized"), 403

    target = User.query.get_or_404(user_id)
    new_password = request.form.get("password", "")
    if not new_password:
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_users"))

    target.set_password(new_password)
    db.session.add(AdminActionLog(admin_username=current_user.username, actor_role=("admin" if current_user.is_admin else "mod"), action="password_change",
                                    target_username=target.username, target_account_id=target.account_id))
    db.session.commit()
    flash(tr("flash_password_changed"))
    return redirect(url_for("admin_users"))


@app.route("/invest", methods=["GET", "POST"])
@login_required
def invest():
    if request.method == "POST":
        try:
            amount = float(request.form["amount"])
        except (ValueError, TypeError, KeyError):
            amount = 0
        try:
            term_days = int(request.form.get("term_days", 7))
        except (ValueError, TypeError):
            term_days = 7
        if term_days not in INVESTMENT_TERMS:
            term_days = next(iter(INVESTMENT_TERMS))

        if amount < INVESTMENT_MIN:
            flash(f"{tr('flash_investment_min')} {format_money(INVESTMENT_MIN)}")
            return redirect(url_for("invest"))

        if current_user.balance < amount:
            flash(tr("flash_insufficient"))
            return redirect(url_for("invest"))

        rate = INVESTMENT_TERMS[term_days]
        current_user.balance -= amount
        payout = amount * (1 + rate / 100)
        matures_at = datetime.utcnow() + timedelta(days=term_days)
        db.session.add(Investment(
            user_id=current_user.id, amount=amount, rate_percent=rate,
            payout=payout, matures_at=matures_at,
        ))
        db.session.commit()
        flash(tr("flash_investment_created"))
        return redirect(url_for("invest"))

    investments = (Investment.query.filter_by(user_id=current_user.id)
                   .order_by(Investment.created_at.desc()).all())
    return page(INVEST_HTML, investments=investments, investment_terms=INVESTMENT_TERMS,
                min_amount=INVESTMENT_MIN)


@app.route("/companies/apply", methods=["GET", "POST"])
@login_required
def company_apply():
    """أي مستخدم عادي بس يقدر يقدّم طلب لتسجيل مصنعه/شركته جوه اللعبة كسهم متداول في السوق.
    الأدمن/المشرف دورهم مراجعة الطلبات والموافقة/الرفض بس، مش التقديم. لما يوافق، بيتحول
    الطلب تلقائي لسهم بالتقسيم: 50% مالك / 10% GNID / 40% سوق."""
    if not COMPANY_FEATURE_ENABLED:
        return page(FEATURE_DISABLED_HTML)
    if current_user.is_admin or current_user.is_mod:
        return tr("not_authorized"), 403

    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        symbol = request.form.get("symbol", "").strip()
        factory_link = request.form.get("factory_link", "").strip()
        try:
            level = int(request.form.get("level", ""))
            capital = float(request.form.get("capital", ""))
            daily_production = float(request.form.get("daily_production", ""))
        except (ValueError, TypeError):
            flash(tr("flash_bad_amount"))
            return redirect(url_for("company_apply"))

        if not company_name or not symbol or not factory_link or level < 0 or capital < 0 or daily_production < 0:
            flash(tr("flash_bad_amount"))
            return redirect(url_for("company_apply"))

        # منع تسجيل نفس المصنع/الشركة مرتين - سواء لسه معلق أو اتوافق عليه بالفعل (لأي مستخدم)
        existing = CompanyRequest.query.filter(
            CompanyRequest.factory_link == factory_link,
            CompanyRequest.status.in_(["pending", "approved"]),
        ).first()
        if existing:
            flash(tr("flash_company_link_already_used"))
            return redirect(url_for("company_apply"))

        db.session.add(CompanyRequest(
            user_id=current_user.id, company_name=company_name, symbol=symbol,
            factory_link=factory_link, level=level, capital=capital, daily_production=daily_production,
        ))
        db.session.commit()
        flash(tr("flash_company_request_sent"))
        return redirect(url_for("company_apply"))

    my_requests = (CompanyRequest.query.filter_by(user_id=current_user.id)
                   .order_by(CompanyRequest.created_at.desc()).all())
    return page(COMPANY_APPLY_HTML, my_requests=my_requests,
                owner_pct=COMPANY_OWNER_PCT, gnid_pct=COMPANY_GNID_PCT, market_pct=COMPANY_MARKET_PCT)


@app.route("/admin/companies")
@login_required
def admin_companies():
    if not COMPANY_FEATURE_ENABLED:
        return page(FEATURE_DISABLED_HTML)
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    requests_list = CompanyRequest.query.order_by(CompanyRequest.created_at.desc()).all()
    return page(ADMIN_COMPANIES_HTML, requests_list=requests_list)


@app.route("/admin/companies/<int:request_id>/approve", methods=["POST"])
@login_required
def admin_company_approve(request_id):
    if not COMPANY_FEATURE_ENABLED:
        return page(FEATURE_DISABLED_HTML)
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    req = CompanyRequest.query.get_or_404(request_id)
    if req.status != "pending":
        return redirect(url_for("admin_companies"))

    valuation = compute_company_valuation(req.level, req.capital, req.daily_production)
    owner_shares = round(COMPANY_TOTAL_SHARES * COMPANY_OWNER_PCT / 100)
    gnid_shares = round(COMPANY_TOTAL_SHARES * COMPANY_GNID_PCT / 100)
    market_supply = COMPANY_TOTAL_SHARES - owner_shares - gnid_shares
    price_per_share = valuation / COMPANY_TOTAL_SHARES

    stock = Stock(symbol=req.symbol, name=req.company_name, admin_price=price_per_share,
                  admin_supply=market_supply, owner_name=req.user.username,
                  owner_account_id=req.user.account_id, total_shares=COMPANY_TOTAL_SHARES,
                  owner_shares=owner_shares, gnid_shares=gnid_shares,
                  creator_username=current_user.username,
                  creator_role=("admin" if current_user.is_admin else "mod"))
    db.session.add(stock)
    db.session.flush()

    req.status = "approved"
    req.computed_valuation = valuation
    req.stock_id = stock.id
    req.handled_at = datetime.utcnow()
    req.handled_by = current_user.username
    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="company_approve", target_username=req.user.username,
                                    target_account_id=req.user.account_id))
    db.session.commit()
    flash(tr("flash_company_approved"))
    return redirect(url_for("admin_companies"))


@app.route("/admin/companies/<int:request_id>/reject", methods=["POST"])
@login_required
def admin_company_reject(request_id):
    if not COMPANY_FEATURE_ENABLED:
        return page(FEATURE_DISABLED_HTML)
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    req = CompanyRequest.query.get_or_404(request_id)
    if req.status != "pending":
        return redirect(url_for("admin_companies"))

    req.status = "rejected"
    req.reject_reason = request.form.get("reason", "").strip()
    req.handled_at = datetime.utcnow()
    req.handled_by = current_user.username
    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="company_reject", target_username=req.user.username,
                                    target_account_id=req.user.account_id))
    db.session.commit()
    flash(tr("flash_company_rejected"))
    return redirect(url_for("admin_companies"))


@app.route("/currencies/apply", methods=["GET", "POST"])
@login_required
def currency_apply():
    """أي مستخدم (عادي أو أدمن/مشرف) يقدر يبعت تقرير عن عملة عايز يصدرها. أدمن تاني بيراجع
    ويوافق أو يرفض. لما يوافق، بيتحدد سعر الوحدة وإجمالي عدد الوحدات، وكل الوحدات بتروح
    100% لصاحب الطلب."""
    if request.method == "POST":
        currency_name = request.form.get("currency_name", "").strip()
        symbol = request.form.get("symbol", "").strip()
        report_text = request.form.get("report_text", "").strip()

        if not currency_name or not symbol or not report_text:
            flash(tr("flash_bad_amount"))
            return redirect(url_for("currency_apply"))

        db.session.add(CurrencyRequest(
            user_id=current_user.id, currency_name=currency_name, symbol=symbol,
            report_text=report_text,
        ))
        db.session.commit()
        flash(tr("flash_currency_request_sent"))
        return redirect(url_for("currency_apply"))

    my_requests = (CurrencyRequest.query.filter_by(user_id=current_user.id)
                   .order_by(CurrencyRequest.created_at.desc()).all())
    return page(CURRENCY_APPLY_HTML, my_requests=my_requests)


@app.route("/admin/currencies")
@login_required
def admin_currencies():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    requests_list = CurrencyRequest.query.order_by(CurrencyRequest.created_at.desc()).all()
    return page(ADMIN_CURRENCIES_HTML, requests_list=requests_list)


@app.route("/admin/currencies/<int:request_id>/approve", methods=["POST"])
@login_required
def admin_currency_approve(request_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    req = CurrencyRequest.query.get_or_404(request_id)
    if req.status != "pending":
        return redirect(url_for("admin_currencies"))

    try:
        unit_price = float(request.form.get("unit_price", ""))
        total_supply = int(request.form.get("total_supply", ""))
    except (ValueError, TypeError):
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_currencies"))
    if unit_price <= 0 or total_supply <= 0:
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_currencies"))

    # العملة بتبدأ بمالك واحد (صاحب الطلب) بـ100% من الوحدات كملكية حقيقية قابلة للتداول -
    # على عكس الشركات، مفيش نصيب محجوز للبنك أو نصيب سوق منفصل (IPO)؛ كل حاجة تتباع بين
    # اللاعبين مباشرة بعد كده لو صاحبها حب يبيع جزء منها.
    stock = Stock(symbol=req.symbol, name=req.currency_name, admin_price=unit_price,
                  admin_supply=0, asset_type="currency", owner_name=req.user.username,
                  owner_account_id=req.user.account_id, total_shares=total_supply,
                  owner_shares=0, gnid_shares=0, creator_username=current_user.username,
                  creator_role=("admin" if current_user.is_admin else "mod"))
    db.session.add(stock)
    db.session.flush()

    db.session.add(Holding(user_id=req.user_id, stock_id=stock.id, quantity=total_supply))

    req.status = "approved"
    req.stock_id = stock.id
    req.handled_at = datetime.utcnow()
    req.handled_by = current_user.username
    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="currency_approve", target_username=req.user.username,
                                    target_account_id=req.user.account_id))
    db.session.commit()
    flash(tr("flash_currency_approved"))
    return redirect(url_for("admin_currencies"))


@app.route("/admin/currencies/<int:request_id>/reject", methods=["POST"])
@login_required
def admin_currency_reject(request_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    req = CurrencyRequest.query.get_or_404(request_id)
    if req.status != "pending":
        return redirect(url_for("admin_currencies"))

    req.status = "rejected"
    req.reject_reason = request.form.get("reason", "").strip()
    req.handled_at = datetime.utcnow()
    req.handled_by = current_user.username
    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="currency_reject", target_username=req.user.username,
                                    target_account_id=req.user.account_id))
    db.session.commit()
    flash(tr("flash_currency_rejected"))
    return redirect(url_for("admin_currencies"))


@app.route("/admin/currencies/<int:stock_id>/distribute", methods=["POST"])
@login_required
def admin_currency_distribute(stock_id):
    """توزيع الإيراد الأسبوعي لعملة: 40% لصاحبها، 10% لأكبر 5 حاملين (بالتناسب مع نسبة
    ملكيتهم من إجمالي الوحدات)، و50% لخزينة GNID (45% إيراد + 5% رسوم صيانة، مسجلين
    كسطرين منفصلين للشفافية)."""
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    stock = Stock.query.get_or_404(stock_id)
    if stock.asset_type != "currency":
        return tr("not_authorized"), 403

    try:
        revenue = float(request.form.get("revenue", ""))
    except (ValueError, TypeError):
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_currencies"))
    if revenue <= 0:
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_currencies"))

    owner = User.query.filter_by(account_id=stock.owner_account_id).first() if stock.owner_account_id else None
    if not owner:
        flash(tr("flash_no_currency_owner"))
        return redirect(url_for("admin_currencies"))

    top5 = (Holding.query.filter_by(stock_id=stock.id).filter(Holding.quantity > 0)
            .order_by(Holding.quantity.desc()).limit(5).all())
    shares_outstanding = stock.shares_outstanding()
    if not top5 or shares_outstanding <= 0:
        flash(tr("flash_no_shareholders_yet"))
        return redirect(url_for("admin_currencies"))

    owner_amount = revenue * 0.40
    top5_fund = revenue * 0.10
    gnid_amount = revenue * 0.45
    maintenance_amount = revenue * 0.05

    owner.balance += owner_amount

    payout = DividendPayout(stock_id=stock.id, net_profit=revenue, dividend_pct=10,
                             total_fund=top5_fund, recipients_count=len(top5),
                             admin_username=current_user.username, owner_amount=owner_amount)
    db.session.add(payout)
    db.session.flush()

    for h in top5:
        amount = top5_fund * (h.quantity / shares_outstanding)
        h.user.balance += amount
        db.session.add(DividendRecipient(payout_id=payout.id, user_id=h.user_id,
                                           shares_at_time=h.quantity, amount=amount))

    db.session.add(TreasuryEntry(amount=gnid_amount, source="currency_revenue"))
    db.session.add(TreasuryEntry(amount=maintenance_amount, source="currency_maintenance_fee"))

    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="currency_revenue", target_username=f"{stock.symbol} {stock.name}",
                                    amount=revenue))
    db.session.commit()
    flash(tr("flash_currency_revenue_distributed"))
    return redirect(url_for("admin_currencies"))


@app.route("/admin/stocks/<int:stock_id>/suspend", methods=["POST"])
@login_required
def admin_stock_suspend(stock_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    stock = Stock.query.get_or_404(stock_id)
    stock.suspended = True
    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="stock_suspend", target_username=f"{stock.symbol} {stock.name}"))
    db.session.commit()
    flash(tr("flash_stock_now_suspended"))
    return redirect(request.referrer or url_for("market"))


@app.route("/admin/stocks/<int:stock_id>/resume", methods=["POST"])
@login_required
def admin_stock_resume(stock_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    stock = Stock.query.get_or_404(stock_id)
    stock.suspended = False
    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="stock_resume", target_username=f"{stock.symbol} {stock.name}"))
    db.session.commit()
    flash(tr("flash_stock_now_resumed"))
    return redirect(request.referrer or url_for("market"))


@app.route("/admin/dividends")
@login_required
def admin_dividends():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    stocks = Stock.query.order_by(Stock.name.asc()).all()
    stocks_info = []
    for s in stocks:
        top5 = (Holding.query.filter_by(stock_id=s.id).filter(Holding.quantity > 0)
                .order_by(Holding.quantity.desc()).limit(5).all())
        recent_stock_payouts = (DividendPayout.query.filter_by(stock_id=s.id)
                                 .order_by(DividendPayout.created_at.desc()).limit(6).all())
        stocks_info.append({"stock": s, "top5": top5, "top5_total": sum(h.quantity for h in top5),
                             "shares_outstanding": s.shares_outstanding(),
                             "recent_payouts": recent_stock_payouts})
    recent_payouts = DividendPayout.query.order_by(DividendPayout.created_at.desc()).limit(30).all()
    return page(ADMIN_DIVIDENDS_HTML, stocks_info=stocks_info, recent_payouts=recent_payouts)


@app.route("/admin/dividends/<int:stock_id>/distribute", methods=["POST"])
@login_required
def admin_dividend_distribute(stock_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    stock = Stock.query.get_or_404(stock_id)

    if not stock.dividend_pct or stock.dividend_pct <= 0:
        flash(tr("flash_dividend_disabled"))
        return redirect(url_for("admin_dividends"))

    try:
        net_profit = float(request.form.get("net_profit", ""))
    except (ValueError, TypeError):
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_dividends"))
    if net_profit <= 0:
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_dividends"))

    # أكبر 5 مساهمين بالكمية - بس اللي معاهم أسهم فعلاً (أكتر من صفر)
    top5 = (Holding.query.filter_by(stock_id=stock.id).filter(Holding.quantity > 0)
            .order_by(Holding.quantity.desc()).limit(5).all())
    if not top5:
        flash(tr("flash_no_shareholders_yet"))
        return redirect(url_for("admin_dividends"))

    # نصيب كل واحد بيتحسب بنسبة ملكيته الحقيقية من إجمالي أسهم الشركة كلها (مش بنسبته
    # بين الـ5 بس) - يعني لو معاه 9.7% من الشركة، ياخد 9.7% من صندوق الأرباح بالظبط،
    # مش نسبة أكبر مصطنعة بس عشان هو من أكبر 5. ده أقرب لواقع توزيع الأرباح الحقيقي
    # (ربح لكل سهم × عدد أسهمه)، والـ"أكبر 5" هنا بس بيحدد مين المستحق للدفع.
    shares_outstanding = stock.shares_outstanding()
    if shares_outstanding <= 0:
        flash(tr("flash_no_shareholders_yet"))
        return redirect(url_for("admin_dividends"))

    total_fund = net_profit * stock.dividend_pct / 100
    payout = DividendPayout(stock_id=stock.id, net_profit=net_profit, dividend_pct=stock.dividend_pct,
                             total_fund=total_fund, recipients_count=len(top5),
                             admin_username=current_user.username)
    db.session.add(payout)
    db.session.flush()

    for h in top5:
        amount = total_fund * (h.quantity / shares_outstanding)
        h.user.balance += amount
        db.session.add(DividendRecipient(payout_id=payout.id, user_id=h.user_id,
                                           shares_at_time=h.quantity, amount=amount))

    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="dividend_distribute", target_username=f"{stock.symbol} {stock.name}",
                                    amount=total_fund))
    db.session.commit()
    flash(tr("flash_dividend_distributed"))
    return redirect(url_for("admin_dividends"))


@app.route("/notifications")
@login_required
def notifications():
    """صفحة الإشعارات العامة للمستخدم - بتعلّم كل الإشعارات كمقروءة أول ما يفتحها."""
    items = Notification.query.order_by(Notification.created_at.desc()).limit(50).all()
    latest_id = db.session.query(db.func.max(Notification.id)).scalar() or 0
    if latest_id > (current_user.last_seen_notification_id or 0):
        current_user.last_seen_notification_id = latest_id
        db.session.commit()
    return page(NOTIFICATIONS_HTML, items=items)


@app.route("/admin/notifications", methods=["GET", "POST"])
@login_required
def admin_notifications():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()
        if not title or not body:
            flash(tr("flash_bad_amount"))
            return redirect(url_for("admin_notifications"))
        db.session.add(Notification(title=title, body=body, admin_username=current_user.username))
        db.session.add(AdminActionLog(admin_username=current_user.username,
                                        actor_role=("admin" if current_user.is_admin else "mod"),
                                        action="notification_send", target_username=title[:80]))
        db.session.commit()
        flash(tr("flash_notification_sent"))
        return redirect(url_for("admin_notifications"))

    items = Notification.query.order_by(Notification.created_at.desc()).limit(50).all()
    return page(ADMIN_NOTIFICATIONS_HTML, items=items)


@app.route("/admin/notifications/<int:notification_id>/delete", methods=["POST"])
@login_required
def admin_notification_delete(notification_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    n = Notification.query.get_or_404(notification_id)
    db.session.delete(n)
    db.session.commit()
    flash(tr("flash_notification_deleted"))
    return redirect(url_for("admin_notifications"))



def process_matured_investments():
    """بتتنفذ كل دقيقة: تدور على الاستثمارات اللي وصلت لتاريخ استحقاقها وتضيف العائد تلقائيًا."""
    with app.app_context():
        try:
            due = Investment.query.filter(
                Investment.status == "active",
                Investment.matures_at <= datetime.utcnow(),
            ).all()
            for inv in due:
                user = User.query.get(inv.user_id)
                if user:
                    user.balance += inv.payout
                inv.status = "paid"
                inv.paid_at = datetime.utcnow()
            if due:
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            log.error(f"process_matured_investments err: {e}")
        finally:
            db.session.remove()


def process_loan_due_dates():
    """بتتنفذ بشكل دوري (كل 15 دقيقة):
    1) تبعت تحذير (تليجرام) لأي دين موافق عليه باقي على استحقاقه يوم واحد بس (مرة واحدة بس لكل دين).
    2) لو ميعاد السداد فات فعلاً ولسه متسددش: لو معاه رصيد كفاية، بيتسحب المبلغ تلقائي ويتسدد الدين.
       لو رصيده مش كفاية، بيتجمد حسابه (يتمنع من السحب والتداول وطلب دين جديد) لحد ما يتسدد.
    3) أي حساب مجمّد بسبب دين، أول ما آخر دين متأخر عليه يتسدد (تلقائي أو يدوي)، بيتفك تجميده تلقائي."""
    with app.app_context():
        try:
            now = datetime.utcnow()

            # 1) تذكير قبل الاستحقاق بيوم واحد
            due_soon = LoanRequest.query.filter(
                LoanRequest.status == "approved",
                LoanRequest.due_date.isnot(None),
                LoanRequest.due_date <= now + timedelta(days=1),
                LoanRequest.due_date > now,
                LoanRequest.reminder_sent.is_(False),
            ).all()
            for loan in due_soon:
                user = loan.user
                amount_due = loan.repay_amount or loan.amount
                if user and user.telegram_verified and user.telegram_chat_id:
                    send_telegram_dm(user.telegram_chat_id, tr_bg("bot_loan_due_reminder_msg").format(
                        amount=format_money(amount_due), due_date=loan.due_date.strftime("%Y-%m-%d")))
                loan.reminder_sent = True
            if due_soon:
                db.session.commit()

            # 2) إنفاذ الاستحقاق: سحب تلقائي لو فيه رصيد، وإلا تجميد الحساب
            overdue = LoanRequest.query.filter(
                LoanRequest.status == "approved",
                LoanRequest.due_date.isnot(None),
                LoanRequest.due_date <= now,
            ).order_by(LoanRequest.due_date.asc()).all()
            for loan in overdue:
                user = loan.user
                if not user:
                    continue
                amount_due = loan.repay_amount or loan.amount
                if user.balance >= amount_due:
                    user.balance -= amount_due
                    loan.status = "repaid"
                    loan.repaid_at = now
                    db.session.add(TreasuryEntry(amount=amount_due, source="loan_repayment_auto"))
                    if user.telegram_verified and user.telegram_chat_id:
                        send_telegram_dm(user.telegram_chat_id, tr_bg("bot_loan_auto_repaid_msg").format(amount=format_money(amount_due)))
                elif not user.is_frozen:
                    user.is_frozen = True
                    user.frozen_reason = "unpaid_loan"
                    if user.telegram_verified and user.telegram_chat_id:
                        send_telegram_dm(user.telegram_chat_id, tr_bg("bot_loan_frozen_msg").format(amount=format_money(amount_due)))
            if overdue:
                db.session.commit()

            # 3) فك التجميد التلقائي عن أي حساب مبقاش عنده ديون متأخرة السداد
            still_overdue_user_ids = {row[0] for row in db.session.query(LoanRequest.user_id).filter(
                LoanRequest.status == "approved", LoanRequest.due_date.isnot(None), LoanRequest.due_date <= now).all()}
            frozen_users = User.query.filter_by(is_frozen=True).all()
            unfrozen_any = False
            for u in frozen_users:
                if u.id not in still_overdue_user_ids:
                    u.is_frozen = False
                    u.frozen_reason = None
                    unfrozen_any = True
            if unfrozen_any:
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            log.error(f"process_loan_due_dates err: {e}")
        finally:
            db.session.remove()


def apply_market_pressure_pricing():
    """بتتنفذ كل ساعة: بتحسب الضغط (عرض/طلب) من الأوامر المفتوحة لكل سهم، وبتحرك السعر
    تلقائيًا في اتجاه الضغط ده بحد أقصى ±2% في الدورة الواحدة - حتى لو محصلش أي صفقة فعلية.
    الحساب بالكمية: (مجموع كمية الشراء المفتوحة - مجموع كمية البيع المفتوحة) / إجمالي الكمية.
    لو إجمالي الكمية المفتوحة (بيع+شراء) أقل من حد أدنى معين، مفيش حركة خالص - عشان مع
    قلة عدد اللاعبين حاليًا، شخص واحد بأمر صغير ميقدرش يحرك السعر بمفرده من غير سيولة حقيقية.
    الحركة بتتسجل كصفقة رمزية (quantity=0) عشان تتظهر كـ"السعر الحالي" بنفس آلية آخر صفقة
    المستخدمة في كل حسابات التطبيق، من غير ما تأثر على حجم التداول الحقيقي."""
    with app.app_context():
        try:
            stocks = Stock.query.filter_by(suspended=False).all()
            for stock in stocks:
                buy_qty = db.session.query(db.func.coalesce(db.func.sum(Order.quantity), 0)).filter(
                    Order.stock_id == stock.id, Order.side == "buy", Order.status == "open"
                ).scalar() or 0
                sell_qty = db.session.query(db.func.coalesce(db.func.sum(Order.quantity), 0)).filter(
                    Order.stock_id == stock.id, Order.side == "sell", Order.status == "open"
                ).scalar() or 0

                total_qty = buy_qty + sell_qty
                if total_qty < MARKET_PRESSURE_MIN_LIQUIDITY:
                    continue  # سيولة مفتوحة قليلة جدًا - مش إشارة كافية نحرك السعر عليها

                pressure_ratio = (buy_qty - sell_qty) / total_qty  # من -1 (بيع بحت) لـ +1 (شراء بحت)
                move_pct = pressure_ratio * MARKET_PRESSURE_MAX_MOVE_PCT
                if move_pct == 0:
                    continue  # توازن تام - مفيش داعي لحركة

                current_price = stock.price_stats()["current"]
                if current_price <= 0:
                    continue
                new_price = current_price * (1 + move_pct / 100)

                db.session.add(Trade(
                    stock_id=stock.id, buyer_id=None, seller_id=None,
                    quantity=0, price=new_price, fee=0, source="pressure",
                ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            log.error(f"apply_market_pressure_pricing err: {e}")
        finally:
            db.session.remove()


@app.route("/debts", methods=["GET", "POST"])
@login_required
def debts():
    if request.method == "POST":
        if not current_user.telegram_verified:
            flash(tr("flash_loan_needs_verification"))
            return redirect(url_for("settings") + "#verify-panel")
        if current_user.is_frozen:
            flash(tr("flash_account_frozen"))
            return redirect(url_for("debts"))
        try:
            amount = float(request.form["amount"])
        except (ValueError, TypeError, KeyError):
            amount = 0
        try:
            term_days = int(request.form.get("term_days", 3))
        except (ValueError, TypeError):
            term_days = 3
        reason = request.form.get("reason", "").strip()

        if amount <= 0:
            flash(tr("flash_bad_amount"))
            return redirect(url_for("debts"))
        if term_days not in LOAN_TERMS:
            term_days = 3

        db.session.add(LoanRequest(user_id=current_user.id, amount=amount, reason=reason,
                                    term_days=term_days, interest_pct=LOAN_TERMS[term_days]))
        db.session.commit()
        flash(tr("flash_loan_submitted"))
        return redirect(url_for("debts"))

    loans = (LoanRequest.query.filter_by(user_id=current_user.id)
             .order_by(LoanRequest.created_at.desc()).all())
    return page(DEBTS_HTML, contacts=DEBT_CONTACTS, loans=loans, loan_terms=LOAN_TERMS)


@app.route("/admin/loans")
@login_required
def admin_loans():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    all_loans = LoanRequest.query.order_by(LoanRequest.created_at.desc()).all()
    pending_loans = [l for l in all_loans if l.status == "pending"]
    approved_loans = [l for l in all_loans if l.status == "approved"]  # معتمد ولسه ماتسددش
    repaid_loans = [l for l in all_loans if l.status == "repaid"]      # اتسدد بالكامل
    rejected_loans = [l for l in all_loans if l.status == "rejected"]
    return page(ADMIN_LOANS_HTML, pending_loans=pending_loans, approved_loans=approved_loans,
                repaid_loans=repaid_loans, rejected_loans=rejected_loans)


@app.route("/admin/loans/<int:loan_id>/approve", methods=["POST"])
@login_required
def admin_loan_approve(loan_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    loan = LoanRequest.query.get_or_404(loan_id)
    if loan.status == "pending":
        loan.user.balance += loan.amount
        loan.status = "approved"
        loan.handled_at = datetime.utcnow()
        loan.handled_by = current_user.username
        loan.due_date = loan.handled_at + timedelta(days=loan.term_days)
        loan.repay_amount = loan.amount * (1 + loan.interest_pct / 100)
        db.session.add(AdminActionLog(admin_username=current_user.username,
                                        actor_role=("admin" if current_user.is_admin else "mod"),
                                        action="loan_approve", target_username=loan.user.username,
                                        target_account_id=loan.user.account_id, amount=loan.amount))
        db.session.commit()
        flash(tr("flash_loan_approved"))
    return redirect(url_for("admin_loans"))


@app.route("/admin/loans/<int:loan_id>/reject", methods=["POST"])
@login_required
def admin_loan_reject(loan_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    loan = LoanRequest.query.get_or_404(loan_id)
    if loan.status == "pending":
        loan.status = "rejected"
        loan.handled_at = datetime.utcnow()
        loan.handled_by = current_user.username
        db.session.add(AdminActionLog(admin_username=current_user.username,
                                        actor_role=("admin" if current_user.is_admin else "mod"),
                                        action="loan_reject", target_username=loan.user.username,
                                        target_account_id=loan.user.account_id, amount=loan.amount))
        db.session.commit()
        flash(tr("flash_loan_rejected"))
    return redirect(url_for("admin_loans"))


@app.route("/debts/<int:loan_id>/repay", methods=["POST"])
@login_required
def repay_loan(loan_id):
    loan = LoanRequest.query.get_or_404(loan_id)
    if loan.user_id != current_user.id:
        return tr("not_authorized"), 403
    if loan.status != "approved":
        return redirect(url_for("debts"))

    if current_user.balance < loan.repay_amount:
        flash(tr("flash_loan_repay_insufficient"))
        return redirect(url_for("debts"))

    current_user.balance -= loan.repay_amount
    loan.status = "repaid"
    loan.repaid_at = datetime.utcnow()
    db.session.add(TreasuryEntry(amount=loan.repay_amount, source="loan_repayment"))
    db.session.commit()
    flash(tr("flash_loan_repaid"))
    return redirect(url_for("debts"))


@app.route("/admin/treasury")
@login_required
def admin_treasury():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    entries = TreasuryEntry.query.order_by(TreasuryEntry.created_at.desc()).limit(200).all()
    balance = db.session.query(db.func.coalesce(db.func.sum(TreasuryEntry.amount), 0)).scalar() or 0

    stocks = Stock.query.all()
    treasury_holdings = []
    stocks_value = 0
    for s in stocks:
        if s.gnid_shares and s.gnid_shares > 0:
            price = s.price_stats()["current"]
            value = s.gnid_shares * price
            stocks_value += value
            treasury_holdings.append({"stock": s, "price": price, "value": value})
    treasury_holdings.sort(key=lambda h: h["value"], reverse=True)

    # التزامات مالية على البنك: فلوس مستثمرة ومفروض ترجع، وديون موافق عليها لسه ماتسددتش
    active_investments = Investment.query.filter_by(status="active").all()
    total_invested_active = sum(i.amount for i in active_investments)
    total_investment_payout_due = sum(i.payout for i in active_investments)
    outstanding_loans = LoanRequest.query.filter_by(status="approved").all()
    total_loans_owed = sum((l.repay_amount or l.amount) for l in outstanding_loans)

    vault = Vault.query.get(1)

    return page(ADMIN_TREASURY_HTML, entries=entries, balance=balance, fee_percent=TRADING_FEE_PERCENT,
                stocks=stocks, treasury_holdings=treasury_holdings, stocks_value=stocks_value, vault=vault,
                total_invested_active=total_invested_active, total_investment_payout_due=total_investment_payout_due,
                total_loans_owed=total_loans_owed)


@app.route("/admin/vault/history")
@login_required
def admin_vault_history():
    """سجل حركات حساب الخزنة الحقيقي جوه اللعبة (داخل وخارج) - مجلوب مباشرة من اللعبة نفسها، بلا استثناء."""
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403

    vault = Vault.query.get(1)
    entries, error = [], None
    if vault and vault.token:
        page_num = request.args.get("page", 1, type=int)
        entries, error = fetch_vault_economy_history(vault.token, page=page_num, limit=50)
        # لكل إيداع داخل (income)، نفك منه آي دي الحساب المفروض إنه اتحول له بنفس الطريقة
        # اللي بيستخدمها check_vault_deposits بالظبط، عشان الأدمن يشوف على طول مين المفروض
        # ياخد الفلوس دي، وكمان يلاحظ فورًا لو إيداع معين مش متربط بحساب حقيقي.
        for entry in entries:
            if entry.get("category") == "transfer_in":
                acc_id, credited = decode_deposit(int(entry.get("amount") or 0))
                matched_user = User.query.filter_by(account_id=acc_id).first() if acc_id else None
                entry["matched_user"] = matched_user
                if not matched_user:
                    ext_id = str(entry.get("id")) if entry.get("id") is not None else None
                    dep = Deposit.query.filter_by(external_id=ext_id).first() if ext_id else None
                    entry["refunded"] = bool(dep and dep.status == "refunded")
    else:
        error = tr("flash_auto_send_no_token")

    return page(ADMIN_VAULT_HISTORY_HTML, entries=entries, error=error, vault=vault,
                page_num=request.args.get("page", 1, type=int))


@app.route("/admin/treasury/transfer-shares", methods=["POST"])
@login_required
def admin_treasury_transfer_shares():
    if not current_user.is_admin:
        return tr("not_authorized"), 403

    stock = Stock.query.get_or_404(request.form.get("stock_id"))
    direction = request.form.get("direction", "to_treasury")
    try:
        quantity = int(request.form["quantity"])
    except (ValueError, TypeError, KeyError):
        quantity = 0

    if quantity <= 0:
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_treasury"))

    if direction == "from_treasury":
        if stock.gnid_shares < quantity:
            flash(tr("flash_not_enough_shares"))
            return redirect(url_for("admin_treasury"))
        stock.gnid_shares -= quantity
        stock.admin_supply += quantity
    else:
        if stock.admin_supply < quantity:
            flash(tr("flash_not_enough_shares"))
            return redirect(url_for("admin_treasury"))
        stock.admin_supply -= quantity
        stock.gnid_shares += quantity

    db.session.add(AdminActionLog(admin_username=current_user.username, actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="shares_to_treasury" if direction == "to_treasury" else "shares_from_treasury",
                                    target_username=f"{stock.symbol} {stock.name}",
                                    amount=quantity))
    db.session.commit()
    flash(tr("flash_shares_transferred"))
    return redirect(url_for("admin_treasury"))


@app.route("/admin/treasury/transfer-funds", methods=["POST"])
@login_required
def admin_treasury_transfer_funds():
    if not current_user.is_admin:
        return tr("not_authorized"), 403

    account_id = request.form.get("account_id", "").strip()
    target = User.query.filter_by(account_id=account_id).first()
    try:
        amount = float(request.form["amount"])
    except (ValueError, TypeError, KeyError):
        amount = 0

    if not target:
        flash(tr("flash_no_recipient"))
        return redirect(url_for("admin_treasury"))
    if amount <= 0:
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_treasury"))

    treasury_balance = db.session.query(db.func.coalesce(db.func.sum(TreasuryEntry.amount), 0)).scalar() or 0
    if treasury_balance < amount:
        flash(tr("flash_insufficient_treasury"))
        return redirect(url_for("admin_treasury"))

    target.balance += amount
    db.session.add(TreasuryEntry(amount=-amount, source="admin_payout"))
    db.session.add(AdminActionLog(admin_username=current_user.username, actor_role="admin",
                                    action="treasury_payout", target_username=target.username,
                                    target_account_id=target.account_id, amount=amount))
    db.session.commit()
    flash(tr("flash_treasury_transferred"))
    return redirect(url_for("admin_treasury"))


@app.route("/settings")
@login_required
def settings():
    bot_username = None
    verify_link = None
    if not (current_user.is_admin or current_user.is_mod):
        bot_username = get_bot_username()
        if bot_username and current_user.telegram_verify_code:
            verify_link = f"https://t.me/{bot_username}?start={current_user.telegram_verify_code}"
    return page(SETTINGS_HTML, bot_username=bot_username, verify_link=verify_link)


@app.route("/guide")
@login_required
def guide():
    return page(GUIDE_HTML)


@app.route("/settings/telegram/verify/generate", methods=["POST"])
@login_required
def settings_generate_verify_code():
    if current_user.is_admin or current_user.is_mod:
        return tr("not_authorized"), 403
    current_user.telegram_verify_code = secrets.token_hex(4)
    db.session.commit()
    return redirect(url_for("settings") + "#verify-panel")


@app.route("/settings/password", methods=["POST"])
@login_required
def settings_change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not current_user.check_password(current_password):
        flash(tr("flash_wrong_current_password"))
        return redirect(url_for("settings") + "#password-panel")

    if new_password != confirm_password:
        flash(tr("flash_passwords_dont_match"))
        return redirect(url_for("settings") + "#password-panel")

    if len(new_password) < 6:
        flash(tr("flash_password_too_short"))
        return redirect(url_for("settings") + "#password-panel")

    current_user.set_password(new_password)
    db.session.commit()
    flash(tr("flash_password_changed_self"))
    return redirect(url_for("settings") + "#password-panel")


@app.route("/settings/username", methods=["POST"])
@login_required
def settings_change_username():
    if current_user.username_changed:
        flash(tr("flash_username_already_used"))
        return redirect(url_for("settings") + "#username-panel")
    if current_user.telegram_verified:
        flash(tr("flash_username_locked_verified"))
        return redirect(url_for("settings") + "#username-panel")

    new_username = request.form.get("username", "").strip()
    if not new_username:
        flash(tr("flash_username_empty"))
        return redirect(url_for("settings") + "#username-panel")

    if new_username.lower() == current_user.username.lower():
        flash(tr("flash_username_empty"))
        return redirect(url_for("settings") + "#username-panel")

    existing = User.query.filter(func.lower(User.username) == new_username.lower(), User.id != current_user.id).first()
    if existing:
        flash(tr("flash_username_taken"))
        return redirect(url_for("settings") + "#username-panel")

    current_user.username = new_username
    current_user.username_changed = True
    db.session.commit()
    flash(tr("flash_username_changed"))
    return redirect(url_for("settings") + "#username-panel")


@app.route("/settings/telegram", methods=["POST"])
@login_required
def settings_change_telegram():
    if current_user.telegram_verified:
        flash(tr("flash_telegram_locked"))
        return redirect(url_for("settings") + "#telegram-panel")

    telegram_username = request.form.get("telegram_username", "").strip().lstrip("@")
    if not telegram_username:
        flash(tr("flash_telegram_empty"))
        return redirect(url_for("settings") + "#telegram-panel")
    if not is_valid_telegram_username(telegram_username):
        flash(tr("flash_telegram_invalid_format"))
        return redirect(url_for("settings") + "#telegram-panel")

    current_user.telegram_username = telegram_username
    db.session.commit()
    flash(tr("flash_telegram_updated"))
    return redirect(url_for("settings") + "#telegram-panel")


def sync_telegram_username(chat_id, real_username, real_first_name):
    """بتحدّث يوزر التليجرام المخزّن لأي حساب موثّق وقت ما يوصلنا أي تفاعل منه (رسالة أو
    ضغطة زرار) - لو غيّر يوزره العام في تليجرام، أو عمل يوزر عام جديد بعد ما كان موثق
    من غيره، أو شاله خالص. كده لوحة الأدمن تفضل مطابقة لشكله الحقيقي في تليجرام حتى لو
    غيّره بعد التوثيق، من غير ما يحتاج يوثق حسابه تاني."""
    linked_user = User.query.filter_by(telegram_chat_id=str(chat_id)).first()
    if not linked_user or not linked_user.telegram_verified:
        return
    had_no_username = not linked_user.telegram_has_username
    if real_username and linked_user.telegram_username != real_username:
        linked_user.telegram_username = real_username
        linked_user.telegram_has_username = True
        db.session.commit()
        if had_no_username:
            send_telegram_dm(chat_id, tr("telegram_bot_username_synced_msg").format(username=real_username))
    elif not real_username and real_first_name and linked_user.telegram_has_username:
        # كان عنده يوزر عام وشاله - نرجع لاسمه الأول عشان الرابط يفضل شغال
        linked_user.telegram_username = real_first_name
        linked_user.telegram_has_username = False
        db.session.commit()


@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    """بيستقبل رسائل بوت التوثيق من تليجرام. لو المستخدم بعت /start <code> أو /verify <code>
    وكان الكود ده متسجل لحساب معين، بنوثق الحساب ده ونربطه بمحادثة تليجرام دي.
    كمان بيستقبل /menu وضغطات أزرار القائمة (الرصيد والإحصائيات، طريقة الإيداع)."""
    if TELEGRAM_WEBHOOK_SECRET:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header != TELEGRAM_WEBHOOK_SECRET:
            return "forbidden", 403

    try:
        update = request.get_json(force=True, silent=True) or {}
    except Exception:
        return "ok", 200

    site_url = request.url_root.rstrip("/")

    # --- ضغطة على زرار من قائمة /menu ---
    callback = update.get("callback_query")
    if callback:
        callback_id = callback.get("id")
        chat = (callback.get("message") or {}).get("chat") or {}
        chat_id = chat.get("id")
        data = callback.get("data", "")
        clicker = callback.get("from") or {}
        answer_telegram_callback(callback_id)
        if not chat_id:
            return "ok", 200

        # نحدّث يوزر التليجرام هنا كمان (مش بس لما يبعت رسالة نصية) عشان المستخدم اللي
        # بيتفاعل بس بالأزرار (زي "My Balance & Stats") يفضل يوزره متزامن برضه.
        sync_telegram_username(chat_id, (clicker.get("username") or "").strip(),
                                (clicker.get("first_name") or "").strip())

        user = User.query.filter_by(telegram_chat_id=str(chat_id)).first()

        if data == "balance_stats":
            if not user:
                send_telegram_dm(chat_id, tr("bot_not_verified_msg"))
                return "ok", 200
            active_investments = Investment.query.filter_by(user_id=user.id, status="active").all()
            total_invested = sum(i.amount for i in active_investments)
            total_expected_payout = sum(i.payout for i in active_investments)
            stocks_owned = Holding.query.filter_by(user_id=user.id).filter(Holding.quantity > 0).count()
            pending_withdrawals = WithdrawalRequest.query.filter_by(user_id=user.id, status="pending").count()
            msg = tr("bot_stats_msg").format(
                username=user.username,
                balance=format_money(user.balance),
                active_count=len(active_investments),
                total_invested=format_money(total_invested),
                total_payout=format_money(total_expected_payout),
                stocks_owned=stocks_owned,
                pending_withdrawals=pending_withdrawals,
            )
            send_telegram_dm(chat_id, msg)
        elif data == "how_deposit":
            send_telegram_dm(chat_id, tr("bot_deposit_help_msg").format(site_url=site_url))
        return "ok", 200

    message = update.get("message") or update.get("edited_message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    sender = message.get("from") or {}
    real_username = (sender.get("username") or "").strip()  # اليوزرنيم الحقيقي بتاع صاحب الحساب فعليًا (مش نص بيكتبه هو)
    real_first_name = (sender.get("first_name") or "").strip()  # احتياطي لو الحساب مفهوش يوزرنيم عام أصلاً
    if not chat_id or not text:
        return "ok", 200

    sync_telegram_username(chat_id, real_username, real_first_name)

    parts = text.split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    code = parts[1].strip() if len(parts) > 1 else ""

    # رسالة الترحيب بتقول للمستخدم "send me that code here" - من غير ما تطلب منه أي أمر
    # زي /verify قبلها. فعليًا كتير من المستخدمين بيبعتوا الكود لوحده كنص عادي، وكان
    # بيتجاهل بالكامل (مفيش رد ولا توثيق) لأن الشرط تحت كان بيقبل بس /start أو /verify.
    # هنا بنتعرف على أي نص شكله كود توثيق (8 حروف hex زي اللي بيتولد فعليًا) ونعامله
    # بالظبط زي /verify <code>.
    if not text.startswith("/") and TELEGRAM_VERIFY_CODE_RE.match(text):
        command = "/verify"
        code = text

    if command == "/menu":
        send_telegram_menu(chat_id, site_url)
    elif command in ("/start", "/verify") and code:
        already = User.query.filter_by(telegram_chat_id=str(chat_id)).first()
        if already and not already.telegram_verify_code == code:
            send_telegram_dm(chat_id, tr("telegram_bot_already_linked"))
            return "ok", 200

        target = User.query.filter_by(telegram_verify_code=code).first()
        if not target:
            send_telegram_dm(chat_id, tr("telegram_bot_invalid_code"))
            return "ok", 200
        if target.is_admin or target.is_mod:
            # الأدمن والمشرف ممنوعين من التوثيق أصلاً - حماية إضافية هنا حتى لو حصل كود بطريقة ما
            send_telegram_dm(chat_id, tr("telegram_bot_invalid_code"))
            return "ok", 200
        if not real_username:
            # مفيش يوزر عام (@) للحساب ده - مش بنوثق خالص، وبنسيب الكود شغال عشان يرجع بعد
            # ما يعمل يوزر من إعدادات تليجرام نفسه (Settings → Username) ويبعت نفس الكود تاني
            send_telegram_dm(chat_id, tr("telegram_bot_need_username_first"))
            return "ok", 200

        target.telegram_verified = True
        target.telegram_chat_id = str(chat_id)
        target.telegram_verify_code = None
        target.telegram_username = real_username
        target.telegram_has_username = True
        db.session.commit()
        send_telegram_dm(chat_id, tr("telegram_bot_verified_msg").format(username=target.username))
    elif command in ("/start", "/verify"):
        send_telegram_dm(chat_id, tr("telegram_bot_welcome_msg"))
    return "ok", 200


@app.route("/admin/telegram/setup", methods=["POST"])
@login_required
def admin_telegram_setup():
    if not current_user.is_admin:
        return tr("not_authorized"), 403
    if not TELEGRAM_BOT_TOKEN:
        flash(tr("flash_telegram_token_missing"))
        return redirect(url_for("settings") + "#bot-setup-panel")

    webhook_url = request.url_root.rstrip("/") + url_for("telegram_webhook")
    payload = {"url": webhook_url}
    if TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = TELEGRAM_WEBHOOK_SECRET
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
                          data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            flash(tr("flash_telegram_webhook_set"))
        else:
            flash(f"{tr('flash_telegram_webhook_failed')}: {result.get('description', '')}")
    except Exception as e:
        flash(f"{tr('flash_telegram_webhook_failed')}: {e}")
    return redirect(url_for("settings") + "#bot-setup-panel")


@app.route("/admin/export/backup")
@login_required
def admin_export_backup():
    """يصدّر نسخة احتياطية كاملة (JSON) لكل البيانات الحساسة: المستخدمين (الرصيد، يوزر التليجرام)،
    الاستثمارات، الأسهم المملوكة، طلبات الديون والسحب، وسجل الخزينة - عشان تكون موجودة لو حصل فقدان بيانات."""
    if not current_user.is_admin:
        return tr("not_authorized"), 403

    def iso(dt):
        return dt.isoformat() if dt else None

    users_data = []
    for u in User.query.order_by(db.cast(User.account_id, db.Integer).asc()).all():
        users_data.append({
            "account_id": u.account_id, "username": u.username,
            "telegram_username": u.telegram_username, "telegram_verified": u.telegram_verified,
            "telegram_has_username": u.telegram_has_username, "telegram_chat_id": u.telegram_chat_id,
            "balance": u.balance, "is_admin": u.is_admin, "is_mod": u.is_mod, "is_frozen": u.is_frozen,
        })

    holdings_data = [{
        "account_id": h.user.account_id if h.user else None,
        "username": h.user.username if h.user else None,
        "stock_symbol": h.stock.symbol, "stock_name": h.stock.name, "quantity": h.quantity,
    } for h in Holding.query.all()]

    investments_data = [{
        "account_id": i.user.account_id if i.user else None,
        "username": i.user.username if i.user else None,
        "amount": i.amount, "rate_percent": i.rate_percent, "payout": i.payout, "status": i.status,
        "is_manual": i.is_manual, "created_at": iso(i.created_at), "matures_at": iso(i.matures_at),
        "paid_at": iso(i.paid_at),
    } for i in Investment.query.all()]

    loans_data = [{
        "account_id": l.user.account_id if l.user else None,
        "username": l.user.username if l.user else None,
        "amount": l.amount, "term_days": l.term_days, "interest_pct": l.interest_pct,
        "repay_amount": l.repay_amount, "status": l.status, "reason": l.reason,
        "created_at": iso(l.created_at), "due_date": iso(l.due_date), "repaid_at": iso(l.repaid_at),
    } for l in LoanRequest.query.all()]

    withdrawals_data = [{
        "account_id": w.user.account_id if w.user else None,
        "username": w.user.username if w.user else None,
        "amount": w.amount, "account_link": w.account_link, "account_name": w.account_name,
        "status": w.status, "created_at": iso(w.created_at), "handled_at": iso(w.handled_at),
    } for w in WithdrawalRequest.query.all()]

    treasury_data = [{
        "amount": t.amount, "source": t.source, "created_at": iso(t.created_at),
    } for t in TreasuryEntry.query.all()]

    stocks_data = [{
        "symbol": s.symbol, "name": s.name, "admin_price": s.admin_price, "admin_supply": s.admin_supply,
        "total_shares": s.total_shares, "owner_shares": s.owner_shares, "gnid_shares": s.gnid_shares,
        "owner_name": s.owner_name, "owner_account_id": s.owner_account_id,
    } for s in Stock.query.all()]

    backup = {
        "exported_at": datetime.utcnow().isoformat(),
        "app_version": APP_VERSION,
        "users": users_data,
        "holdings": holdings_data,
        "investments": investments_data,
        "loans": loans_data,
        "withdrawals": withdrawals_data,
        "treasury_entries": treasury_data,
        "stocks": stocks_data,
    }

    filename = f"gnid_bank_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    db.session.add(AdminActionLog(admin_username=current_user.username, actor_role="admin", action="data_backup_export"))
    db.session.commit()
    return Response(
        json.dumps(backup, ensure_ascii=False, indent=2),
        mimetype="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@app.route("/admin/investments", methods=["GET", "POST"])
@login_required
def admin_investments():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403

    if request.method == "POST":
        if not (current_user.is_admin or current_user.is_mod):
            return tr("not_authorized"), 403

        account_id = request.form.get("account_id", "").strip()
        target = User.query.filter_by(account_id=account_id).first()
        try:
            amount = float(request.form["amount"])
            rate = float(request.form["rate"])
            days_passed = int(request.form["days_passed"])
        except (ValueError, TypeError, KeyError):
            target = None

        if not target:
            flash(tr("flash_no_recipient"))
            return redirect(url_for("admin_investments"))

        started_at = datetime.utcnow() - timedelta(days=days_passed)
        matures_at = started_at + timedelta(days=INVESTMENT_TERM_DAYS)
        payout = amount * (1 + rate / 100)
        db.session.add(Investment(
            user_id=target.id, amount=amount, rate_percent=rate,
            payout=payout, created_at=started_at, matures_at=matures_at,
            is_manual=True, creator_username=current_user.username,
            creator_role=("admin" if current_user.is_admin else "mod"),
        ))
        db.session.add(AdminActionLog(admin_username=current_user.username,
                                        actor_role=("admin" if current_user.is_admin else "mod"),
                                        action="investment_add_manual", target_username=target.username,
                                        target_account_id=target.account_id, amount=amount))
        db.session.commit()
        flash(tr("flash_investment_added_admin"))
        return redirect(url_for("admin_investments"))

    investments = Investment.query.order_by(Investment.created_at.desc()).all()
    return page(ADMIN_INVESTMENTS_HTML, investments=investments, default_rate=INVESTMENT_RATE_PERCENT,
                now=datetime.utcnow())


@app.route("/admin/investments/<int:investment_id>/delete", methods=["POST"])
@login_required
def admin_investment_delete(investment_id):
    inv = Investment.query.get_or_404(investment_id)
    # الأدمن يقدر يحذف أي استثمار. المشرف يقدر يحذف بس الاستثمارات اليدوية اللي
    # هو (أو مشرف تاني) ضافها - مش استثمارات المستخدمين الذاتية ولا اللي ضافها الأدمن.
    if not current_user.is_admin:
        if not (current_user.is_mod and inv.is_manual and inv.creator_role == "mod"):
            return tr("not_authorized"), 403

    target = User.query.get(inv.user_id)
    if inv.status == "active" and not inv.is_manual:
        # الاستثمار لسه شغال ومحجوز منه مبلغ من رصيد صاحبه (استثمار ذاتي بس) - نرجعه له قبل الحذف.
        # الاستثمارات اليدوية مبتخصمش رصيد وقت إضافتها أصلاً، فمفيش حاجة نرجعها هنا.
        if target:
            target.balance += inv.amount
    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="investment_delete",
                                    target_username=target.username if target else "—",
                                    target_account_id=target.account_id if target else "",
                                    amount=inv.amount))
    db.session.delete(inv)
    db.session.commit()
    flash(tr("flash_investment_deleted"))
    return redirect(url_for("admin_investments"))


@app.route("/admin/investments/<int:investment_id>/edit", methods=["POST"])
@login_required
def admin_investment_edit(investment_id):
    inv = Investment.query.get_or_404(investment_id)
    # نفس منطق الحذف بالظبط: الأدمن يقدر يعدّل أي استثمار يدوي، والمشرف بس اللي هو (أو مشرف تاني) ضافه.
    if not inv.is_manual:
        return tr("not_authorized"), 403
    if not current_user.is_admin:
        if not (current_user.is_mod and inv.creator_role == "mod"):
            return tr("not_authorized"), 403

    try:
        amount = float(request.form["amount"])
        rate = float(request.form["rate"])
        days_passed = int(request.form["days_passed"])
    except (ValueError, TypeError, KeyError):
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_investments"))

    if amount <= 0:
        flash(tr("flash_bad_amount"))
        return redirect(url_for("admin_investments"))

    started_at = datetime.utcnow() - timedelta(days=days_passed)
    inv.amount = amount
    inv.rate_percent = rate
    inv.created_at = started_at
    inv.matures_at = started_at + timedelta(days=INVESTMENT_TERM_DAYS)
    inv.payout = amount * (1 + rate / 100)
    db.session.add(AdminActionLog(admin_username=current_user.username,
                                    actor_role=("admin" if current_user.is_admin else "mod"),
                                    action="investment_edit",
                                    target_username=inv.user.username if inv.user else "—",
                                    target_account_id=inv.user.account_id if inv.user else "",
                                    amount=amount))
    db.session.commit()
    flash(tr("flash_investment_updated"))
    return redirect(url_for("admin_investments"))


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    if request.method == "POST":
        if current_user.is_frozen:
            flash(tr("flash_account_frozen"))
            return redirect(url_for("withdraw"))
        account_link = request.form.get("account_link", "").strip()
        account_name = request.form.get("account_name", "").strip()
        try:
            amount = float(request.form["amount"])
        except (ValueError, TypeError, KeyError):
            amount = 0

        if not account_link or amount <= 0:
            flash(tr("flash_bad_amount"))
            return redirect(url_for("withdraw"))

        if not WITHDRAWAL_LINK_RE.match(account_link):
            flash(tr("flash_bad_account_link"))
            return redirect(url_for("withdraw"))

        if current_user.balance < amount:
            flash(tr("flash_insufficient"))
            return redirect(url_for("withdraw"))

        current_user.balance -= amount
        db.session.add(WithdrawalRequest(
            user_id=current_user.id, account_link=account_link, account_name=account_name, amount=amount,
        ))
        db.session.commit()
        flash(tr("flash_withdraw_created"))
        return redirect(url_for("withdraw"))

    withdrawals = (WithdrawalRequest.query.filter_by(user_id=current_user.id)
                   .order_by(WithdrawalRequest.created_at.desc()).all())
    return page(WITHDRAW_HTML, withdrawals=withdrawals)


@app.route("/withdraw/<int:request_id>/cancel", methods=["POST"])
@login_required
def cancel_withdraw(request_id):
    wr = WithdrawalRequest.query.get_or_404(request_id)
    if wr.user_id != current_user.id:
        return tr("not_authorized"), 403
    if wr.status != "pending":
        return redirect(url_for("withdraw"))

    current_user.balance += wr.amount
    wr.status = "cancelled"
    wr.handled_at = datetime.utcnow()
    wr.handled_by = current_user.username
    db.session.commit()
    flash(tr("flash_withdraw_cancelled"))
    return redirect(url_for("withdraw"))


@app.route("/admin/withdrawals")
@login_required
def admin_withdrawals():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    withdrawals = WithdrawalRequest.query.order_by(WithdrawalRequest.created_at.desc()).all()
    return page(ADMIN_WITHDRAWALS_HTML, withdrawals=withdrawals)


@app.route("/admin/deposits")
@login_required
def admin_deposits():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    vault = Vault.query.get(1)
    return page(ADMIN_DEPOSITS_HTML, vault=vault, deposit_unit=DEPOSIT_UNIT)


@app.route("/admin/activity")
@login_required
def admin_activity():
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403

    deposits = (Deposit.query.filter_by(status="confirmed")
                .order_by(Deposit.created_at.desc()).limit(100).all())
    withdrawals = WithdrawalRequest.query.order_by(WithdrawalRequest.created_at.desc()).limit(100).all()
    investments = Investment.query.order_by(Investment.created_at.desc()).limit(100).all()
    loans = LoanRequest.query.order_by(LoanRequest.created_at.desc()).limit(100).all()
    trades = Trade.query.order_by(Trade.created_at.desc()).limit(100).all()
    admin_actions = AdminActionLog.query.order_by(AdminActionLog.created_at.desc()).limit(100).all()

    return page(ADMIN_ACTIVITY_HTML, deposits=deposits, withdrawals=withdrawals,
                investments=investments, loans=loans, trades=trades, admin_actions=admin_actions)


@app.route("/admin/withdrawals/<int:request_id>/done", methods=["POST"])
@login_required
def admin_withdraw_done(request_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    wr = WithdrawalRequest.query.get_or_404(request_id)
    if wr.status == "pending":
        wr.status = "done"
        wr.handled_at = datetime.utcnow()
        wr.handled_by = current_user.username
        db.session.add(AdminActionLog(admin_username=current_user.username,
                                        actor_role=("admin" if current_user.is_admin else "mod"),
                                        action="withdraw_done", target_username=wr.user.username,
                                        target_account_id=wr.user.account_id, amount=wr.amount))
        db.session.commit()
        flash(tr("flash_withdraw_done"))
    return redirect(url_for("admin_withdrawals"))


@app.route("/admin/withdrawals/<int:request_id>/auto-send", methods=["POST"])
@login_required
def admin_withdraw_auto_send(request_id):
    """بيحاول ينفذ تحويل الفلوس داخل اللعبة فعليًا (مش يدوي)، باستخدام توكن الخزنة.
    لو نجح، بيقفل الطلب تلقائي. لو فشل في أي خطوة، بيسيب الطلب معلق عشان يتنفذ يدوي زي العادة."""
    if not current_user.is_admin:
        return tr("not_authorized"), 403

    wr = WithdrawalRequest.query.get_or_404(request_id)
    if wr.status != "pending":
        return redirect(url_for("admin_withdrawals"))

    vault = Vault.query.get(1)
    if not vault or not vault.token:
        flash(tr("flash_auto_send_no_token"))
        return redirect(url_for("admin_withdrawals"))

    numeric_id = extract_player_numeric_id(wr.account_link)
    if not numeric_id:
        flash(tr("flash_auto_send_bad_link"))
        return redirect(url_for("admin_withdrawals"))

    recipient_uuid, recipient_username = resolve_player_uuid(numeric_id, vault.token)
    if not recipient_uuid:
        flash(tr("flash_auto_send_player_not_found"))
        return redirect(url_for("admin_withdrawals"))

    result = send_game_transfer(vault.token, recipient_uuid, wr.amount)
    if not result.get("ok"):
        flash(f"{tr('flash_auto_send_failed')}: {result.get('error', '')}")
        return redirect(url_for("admin_withdrawals"))

    wr.status = "done"
    wr.handled_at = datetime.utcnow()
    wr.handled_by = f"{current_user.username} (auto)"
    db.session.add(AdminActionLog(admin_username=current_user.username, actor_role="admin",
                                    action="withdraw_auto_sent", target_username=wr.user.username,
                                    target_account_id=wr.user.account_id, amount=wr.amount))
    db.session.commit()
    flash(tr("flash_auto_send_success").format(username=recipient_username or wr.user.username))
    return redirect(url_for("admin_withdrawals"))


@app.route("/admin/withdrawals/<int:request_id>/reject", methods=["POST"])
@login_required
def admin_withdraw_reject(request_id):
    if not (current_user.is_admin or current_user.is_mod):
        return tr("not_authorized"), 403
    wr = WithdrawalRequest.query.get_or_404(request_id)
    if wr.status == "pending":
        target = User.query.get(wr.user_id)
        if target:
            target.balance += wr.amount
        wr.status = "rejected"
        wr.handled_at = datetime.utcnow()
        wr.handled_by = current_user.username
        db.session.add(AdminActionLog(admin_username=current_user.username,
                                        actor_role=("admin" if current_user.is_admin else "mod"),
                                        action="withdraw_reject", target_username=wr.user.username,
                                        target_account_id=wr.user.account_id, amount=wr.amount))
        db.session.commit()
        flash(tr("flash_withdraw_rejected"))
    return redirect(url_for("admin_withdrawals"))


def compute_market_index():
    """يبني سلسلة زمنية لإجمالي القيمة السوقية لكل الأسهم مع بعض - نقطة لكل صفقة حقيقية حصلت
    في أي سهم، بترتيب زمني. بيرجع كمان حجم كل صفقة (الكمية) عشان يتعرض كعمود حجم تداول تحت خط السعر.
    زي price_stats() بالظبط، بنستبعد صفقات الطرح الرسمي (IPO) لأنها بسعر ثابت مش ناتج عن
    السوق الحقيقي - لو ضمّيناها، أي عملية شراء IPO كانت هترجّع المؤشر الكلي لقيمة قديمة تانية
    فجأة بنفس مشكلة الشكل المسنن اللي كانت موجودة في شارت السهم الواحد قبل ما نصلحها."""
    stocks = Stock.query.all()
    if not stocks:
        return [], [], []

    shares_outstanding = {s.id: s.shares_outstanding() for s in stocks}
    last_price = {s.id: s.admin_price for s in stocks}

    all_trades = Trade.query.filter(Trade.source != "ipo").order_by(Trade.created_at.asc()).all()
    if not all_trades:
        return [], [], []

    labels, values, volumes = [], [], []
    for t in all_trades:
        last_price[t.stock_id] = t.price
        total_cap = sum(last_price.get(sid, 0) * shares_outstanding.get(sid, 0) for sid in shares_outstanding)
        labels.append(t.created_at.strftime("%m-%d %H:%M"))
        values.append(total_cap)
        volumes.append(t.quantity)
    return labels, values, volumes


@app.route("/market")
@login_required
def market():
    sort = request.args.get("sort", "")
    stocks = Stock.query.all()

    if sort == "gainers":
        stocks.sort(key=lambda s: s.price_stats()["pct"], reverse=True)
    elif sort == "losers":
        stocks.sort(key=lambda s: s.price_stats()["pct"])
    elif sort == "volume":
        stocks.sort(key=lambda s: db.session.query(db.func.coalesce(db.func.sum(Trade.quantity), 0))
                    .filter(Trade.stock_id == s.id).scalar() or 0, reverse=True)
    elif sort == "newest":
        stocks.sort(key=lambda s: s.listed_at or datetime.min, reverse=True)

    # العملات مالهاش نصيب بنك تتباع منه (admin_supply=0 دايمًا)، فمش بتظهر في قسم الطرح
    # الرسمي (IPO) - بس بتفضل موجودة في stocks نفسها عشان تظهر في قائمة السوق العام
    # وتتداول بنفس الفورم بالظبط.
    ipo_stocks = [s for s in stocks if s.asset_type != "currency"]
    currencies = [s for s in stocks if s.asset_type == "currency"]

    index_labels, index_values, index_volumes = compute_market_index()
    index_summary = None
    if index_values:
        current_cap = index_values[-1]
        first_cap = index_values[0]
        change = current_cap - first_cap
        pct = (change / first_cap * 100) if first_cap else 0.0
        index_summary = {"current": current_cap, "change": change, "pct": pct,
                          "total_volume": sum(index_volumes)}
    open_orders = Order.query.filter_by(status="open").order_by(Order.price.asc()).all()
    holdings_lookup = {}
    if open_orders:
        order_user_ids = {o.user_id for o in open_orders}
        for h in Holding.query.filter(Holding.user_id.in_(order_user_ids)).all():
            holdings_lookup.setdefault(h.user_id, {})[h.stock_id] = h.quantity
    my_holdings = {h.stock_id: h.quantity for h in Holding.query.filter_by(user_id=current_user.id).all()}
    my_trades = (Trade.query.filter((Trade.buyer_id == current_user.id) | (Trade.seller_id == current_user.id))
                 .order_by(Trade.created_at.desc()).limit(100).all())
    return page(MARKET_HTML, stocks=stocks, ipo_stocks=ipo_stocks, currencies=currencies,
                orders=open_orders, sort=sort, my_trades=my_trades,
                holdings_lookup=holdings_lookup, my_holdings=my_holdings,
                index_labels=index_labels, index_values=index_values, index_volumes=index_volumes,
                index_summary=index_summary,
                fee_percent=TRADING_FEE_PERCENT)


@app.route("/market/<int:stock_id>")
@login_required
def company_profile(stock_id):
    stock = Stock.query.get_or_404(stock_id)
    stats = stock.price_stats()
    shares_outstanding = stock.shares_outstanding()
    ownership = stock.ownership_breakdown()
    available_pct = (stock.admin_supply / shares_outstanding * 100) if shares_outstanding else 0
    market_cap = stats["current"] * shares_outstanding

    trades = (Trade.query.filter_by(stock_id=stock.id).filter(Trade.source != "ipo")
              .order_by(Trade.created_at.asc()).all())
    chart_points = [{"t": t.created_at.isoformat(), "p": t.price} for t in trades]
    if not trades:
        fallback_t = stock.listed_at.isoformat() if stock.listed_at else datetime.utcnow().isoformat()
        chart_points = [{"t": fallback_t, "p": stock.admin_price}]
    chart_labels = [t.created_at.strftime("%m-%d %H:%M") for t in trades] or [""]

    # سجلات "pressure" مش صفقات حقيقية (كمية 0) - دي مجرد تحديث سعر آلي بناءً على ضغط العرض/الطلب،
    # فمبنعرضهاش كـ"صفقة" في الحجم أو النشاط الأخير، بس بتفضل موجودة في الرسم البياني عشان تعكس حركة السعر
    real_trades = [t for t in trades if t.source != "pressure"]
    total_shares_traded = sum(t.quantity for t in real_trades)
    total_value_traded = sum(t.total_value() for t in real_trades)
    volume = {
        "shares": total_shares_traded,
        "value": total_value_traded,
        "count": len(real_trades),
        "avg_price": (total_value_traded / total_shares_traded) if total_shares_traded else 0,
    }

    recent_trades = list(reversed(real_trades))[:30]
    shareholders = (Holding.query.filter_by(stock_id=stock.id)
                    .filter(Holding.quantity > 0)
                    .order_by(Holding.quantity.desc()).limit(20).all())
    dividend_payouts = (DividendPayout.query.filter_by(stock_id=stock.id)
                        .order_by(DividendPayout.created_at.desc()).limit(10).all())

    return page(COMPANY_PROFILE_HTML, stock=stock, stats=stats, shares_outstanding=shares_outstanding,
                ownership=ownership, available_pct=available_pct, market_cap=market_cap, chart_points=chart_points,
                volume=volume, recent_trades=recent_trades,
                shareholders=shareholders, dividend_payouts=dividend_payouts)


@app.route("/market/rankings")
@login_required
def global_rankings():
    holdings = (Holding.query.filter(Holding.quantity > 0)
                .join(Stock, Holding.stock_id == Stock.id)
                .join(User, Holding.user_id == User.id).all())

    rankings = []
    stock_cache = {}
    for h in holdings:
        if h.stock_id not in stock_cache:
            stock_cache[h.stock_id] = h.stock.shares_outstanding(), h.stock.price_stats()["current"]
        outstanding, current_price = stock_cache[h.stock_id]
        pct = (h.quantity / outstanding * 100) if outstanding else 0
        rankings.append({
            "username": h.user.username,
            "verified": h.user.telegram_verified,
            "stock_id": h.stock_id,
            "stock_name": h.stock.name,
            "quantity": h.quantity,
            "pct": pct,
            "value": h.quantity * current_price,
        })

    rankings.sort(key=lambda r: r["value"], reverse=True)
    return page(GLOBAL_RANKINGS_HTML, rankings=rankings[:50])


@app.route("/market/buy-ipo/<int:stock_id>", methods=["POST"])
@login_required
def buy_from_admin(stock_id):
    if current_user.is_frozen:
        flash(tr("flash_account_frozen"))
        return redirect(url_for("market"))
    stock = Stock.query.get_or_404(stock_id)
    try:
        qty = int(request.form.get("quantity", ""))
    except (ValueError, TypeError):
        flash(tr("flash_qty_unavailable"))
        return redirect(url_for("market"))
    # أسهم الطرح الرسمي (IPO) من البنك نفسه — بلا عمولة، العمولة بتتفرض بس على
    # الصفقات بين الأفراد (سوق التداول تحت)، مش على الشراء المباشر من البنك.
    cost = qty * stock.admin_price
    total_cost = cost

    if qty <= 0 or qty > stock.admin_supply:
        flash(tr("flash_qty_unavailable"))
        return redirect(url_for("market"))
    if current_user.balance < total_cost:
        flash(tr("flash_insufficient"))
        return redirect(url_for("market"))

    current_user.balance -= total_cost
    stock.admin_supply -= qty

    holding = Holding.query.filter_by(user_id=current_user.id, stock_id=stock.id).first()
    if not holding:
        holding = Holding(user_id=current_user.id, stock_id=stock.id, quantity=0)
        db.session.add(holding)
    holding.quantity += qty

    trade = Trade(stock_id=stock.id, buyer_id=current_user.id, seller_id=None,
                  quantity=qty, price=stock.admin_price, fee=0, source="ipo")
    db.session.add(trade)
    db.session.commit()
    flash(f"{tr('flash_bought')} {qty} {stock.symbol}")
    return redirect(url_for("market"))


# ============================================================
# Stocks: peer-to-peer trading
# ============================================================

@app.route("/market/order", methods=["POST"])
@login_required
def place_order():
    if current_user.is_frozen:
        flash(tr("flash_account_frozen"))
        return redirect(url_for("market"))
    try:
        stock_id = int(request.form.get("stock_id", ""))
        side = request.form.get("side", "")
        price = float(request.form.get("price", ""))
        qty = int(request.form.get("quantity", ""))
    except (ValueError, TypeError):
        flash(tr("flash_bad_order_type"))
        return redirect(url_for("market"))

    stock = Stock.query.get_or_404(stock_id)

    if stock.suspended:
        flash(tr("flash_stock_suspended"))
        return redirect(url_for("market"))

    # حماية من التلاعب بالسعر: أي أمر جديد (بيع أو شراء) لازم يكون سعره قريب من السعر
    # الحالي - بلا كده، حد يقدر يحط أمر بيع بسعر بخس جدًا ويخلي السعر المعروض للكل ينهار
    # فورًا لمجرد صفقة صغيرة، حتى لو مفيش تغيير حقيقي في العرض والطلب.
    # العملات (asset_type == 'currency') مستثناة عمدًا - المفروض تتحرك حرة في السوق بلا سقف.
    current_price = stock.price_stats()["current"]
    if current_price > 0 and stock.asset_type != "currency":
        min_allowed = current_price * (1 - PRICE_BAND_PERCENT / 100)
        max_allowed = current_price * (1 + PRICE_BAND_PERCENT / 100)
        if price < min_allowed or price > max_allowed:
            flash(f"{tr('flash_price_out_of_band')} ({format_money(min_allowed)} - {format_money(max_allowed)})")
            return redirect(url_for("market"))

    # حماية من تكرار نفس الأمر: مينفعش نفس المستخدم يحط أكتر من أمرين مطابقين تمامًا
    # (نفس السهم، نفس النوع، نفس السعر، نفس الكمية) في نفس الوقت
    duplicate_count = Order.query.filter_by(
        user_id=current_user.id, stock_id=stock_id, side=side,
        price=price, quantity=qty, status="open",
    ).count()
    if duplicate_count >= 2:
        flash(tr("flash_duplicate_order_limit"))
        return redirect(url_for("market"))

    if side == "sell":
        holding = Holding.query.filter_by(user_id=current_user.id, stock_id=stock.id).first()
        if not holding or holding.quantity < qty:
            flash(tr("flash_no_qty_to_sell"))
            return redirect(url_for("market"))
    elif side == "buy":
        fee_check = price * qty * (1 + TRADING_FEE_PERCENT / 100)
        if current_user.balance < fee_check:
            missing = fee_check - current_user.balance
            flash(f"{tr('flash_insufficient')} — {tr('missing_amount_label')}: {format_money(missing)}")
            return redirect(url_for("market"))
        # نحجز (نخصم) المبلغ كامل وقت إنشاء الأمر - مش وقت التنفيذ - عشان نمنع إنه يستخدم نفس الرصيد
        # في أكتر من أمر شراء في نفس الوقت. لو الأمر اتلغى أو جزء منه فضل مفتوح، بيترجع تلقائي.
        current_user.balance -= fee_check
    else:
        flash(tr("flash_bad_order_type"))
        return redirect(url_for("market"))

    order = Order(user_id=current_user.id, stock_id=stock.id, side=side, price=price, quantity=qty)
    db.session.add(order)
    db.session.commit()

    match_orders(stock.id)
    flash(tr("flash_order_placed"))
    return redirect(url_for("market"))


def match_orders(stock_id):
    stock = Stock.query.get(stock_id)
    if not stock or stock.suspended:
        return
    buys = (Order.query.filter_by(stock_id=stock_id, side="buy", status="open")
            .order_by(Order.price.desc(), Order.created_at.asc()).all())
    sells = (Order.query.filter_by(stock_id=stock_id, side="sell", status="open")
             .order_by(Order.price.asc(), Order.created_at.asc()).all())

    for buy in buys:
        for sell in sells:
            if buy.status != "open" or sell.status != "open":
                continue
            if buy.user_id == sell.user_id:
                continue
            if buy.price < sell.price:
                continue

            # حماية: امنع تنفيذ صفقة بسعر بعيد جدًا عن السعر الحالي. لو حد حاطط أمر بيع
            # قديم من قبل ما السعر يتحرك (بسبب نظام الضغط أو غيره)، تنفيذه فجأة هيرجّع
            # السعر لحتة بعيدة عن الواقع الحالي من غير أي مبرر - فبنسيب الأمرين مفتوحين
            # لحد ما السعر يرجع يقرب منهم، أو صاحبهم يعدّل/يلغي الأمر بنفسه.
            # العملات مستثناة (تتحرك حرة بلا سقف).
            current_price = stock.price_stats()["current"]
            if current_price > 0 and stock.asset_type != "currency":
                min_allowed = current_price * (1 - PRICE_BAND_PERCENT / 100)
                max_allowed = current_price * (1 + PRICE_BAND_PERCENT / 100)
                if sell.price < min_allowed or sell.price > max_allowed:
                    continue

            trade_qty = min(buy.quantity, sell.quantity)
            trade_price = sell.price
            cost = trade_qty * trade_price
            fee = cost * TRADING_FEE_PERCENT / 100

            buyer = User.query.get(buy.user_id)
            seller = User.query.get(sell.user_id)

            # المشتري خصمنا منه المبلغ كامل (بسعر أمره buy.price) وقت ما نزّل الأمر.
            # لو نفّذ بسعر أرخص (سعر أمر البيع)، نرجّعله الفرق هنا.
            escrowed_for_trade = trade_qty * buy.price * (1 + TRADING_FEE_PERCENT / 100)
            refund = escrowed_for_trade - (cost + fee)
            if refund > 0:
                buyer.balance += refund

            seller.balance += cost

            seller_holding = Holding.query.filter_by(user_id=seller.id, stock_id=stock_id).first()
            seller_holding.quantity -= trade_qty

            buyer_holding = Holding.query.filter_by(user_id=buyer.id, stock_id=stock_id).first()
            if not buyer_holding:
                buyer_holding = Holding(user_id=buyer.id, stock_id=stock_id, quantity=0)
                db.session.add(buyer_holding)
            buyer_holding.quantity += trade_qty

            buy.quantity -= trade_qty
            sell.quantity -= trade_qty
            if buy.quantity == 0:
                buy.status = "filled"
            if sell.quantity == 0:
                sell.status = "filled"

            trade = Trade(stock_id=stock_id, buyer_id=buyer.id, seller_id=seller.id,
                          quantity=trade_qty, price=trade_price, fee=fee, source="market")
            db.session.add(trade)
            db.session.flush()
            db.session.add(TreasuryEntry(amount=fee, source="trade_fee", trade_id=trade.id))
            db.session.commit()


@app.route("/market/order/<int:order_id>/cancel", methods=["POST"])
@login_required
def cancel_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id and not current_user.is_admin:
        return tr("not_authorized"), 403
    was_admin_action = order.user_id != current_user.id
    if order.status == "open" and order.side == "buy":
        # نرجّع المبلغ المحجوز على الكمية المتبقية اللي معملتش - لصاحب الأمر نفسه، مش لمين ما ألغاه
        refund = order.price * order.quantity * (1 + TRADING_FEE_PERCENT / 100)
        order.user.balance += refund
    order.status = "cancelled"
    if was_admin_action:
        db.session.add(AdminActionLog(admin_username=current_user.username, actor_role="admin",
                                        action="order_cancelled_by_admin", target_username=order.user.username,
                                        target_account_id=order.user.account_id, amount=order.price * order.quantity))
    db.session.commit()
    return redirect(url_for("market"))


# ============================================================
# ترقية تلقائية للجدول: لو ضفت عمود جديد لأي Model في الكود،
# الدالة دي بتتأكد وقت التشغيل إن العمود موجود فعليًا في الداتابيز،
# ولو مش موجود بتضيفه لوحدها (ALTER TABLE ADD COLUMN) - من غير ما تحتاج
# تدخل SQL Editor يدوي بعد كل تحديث.
# ملاحظة: بتضيف أعمدة جديدة بس؛ مش بتحذف أو تعدل أعمدة موجودة أو تغيّر نوعها.
# ============================================================
def auto_migrate():
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # جدول جديد بالكامل، db.create_all() بيتكفل بيه
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue
            try:
                col_type = col.type.compile(dialect=db.engine.dialect)
                default_clause = ""
                if col.default is not None and getattr(col.default, "arg", None) is not None and not callable(col.default.arg):
                    default_clause = f" DEFAULT {repr(col.default.arg) if isinstance(col.default.arg, str) else col.default.arg}"
                stmt = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}{default_clause}'
                with db.engine.begin() as conn:
                    conn.execute(text(stmt))
                log.info(f"auto_migrate: تمت إضافة العمود '{col.name}' لجدول '{table.name}'")
            except Exception as e:
                log.error(f"auto_migrate: فشل إضافة العمود '{col.name}' لجدول '{table.name}': {e}")

    # عمود trade.buyer_id كان NOT NULL من الأول - بنشيل القيد ده عشان نقدر نحذف حسابات
    # المستخدمين من غير ما نمسح سجل الصفقات التاريخي (Trade) المرتبط بيهم
    if "trade" in existing_tables:
        try:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE "trade" ALTER COLUMN "buyer_id" DROP NOT NULL'))
            log.info("auto_migrate: تم فك قيد NOT NULL عن trade.buyer_id")
        except Exception as e:
            log.info(f"auto_migrate: تخطي فك قيد trade.buyer_id (على الأغلب اتفك قبل كده): {e}")


# ============================================================
# إعداد أول تشغيل: إنشاء الجداول + إنشاء/ترقية حساب الأدمن من Environment Variables
# ============================================================
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_TELEGRAM = os.environ.get("ADMIN_TELEGRAM", "admin")

MOD_USERNAME = os.environ.get("MOD_USERNAME")
MOD_PASSWORD = os.environ.get("MOD_PASSWORD")
MOD_TELEGRAM = os.environ.get("MOD_TELEGRAM", "mod")

with app.app_context():
    db.create_all()
    auto_migrate()

    if ADMIN_USERNAME and ADMIN_PASSWORD:
        admin_user = User.query.filter_by(username=ADMIN_USERNAME).first()
        if not admin_user:
            admin_user = User(
                username=ADMIN_USERNAME,
                telegram_username=ADMIN_TELEGRAM,
                account_id=generate_account_id(),
                is_admin=True,
            )
            admin_user.set_password(ADMIN_PASSWORD)
            db.session.add(admin_user)
            log.info(f"تم إنشاء حساب الأدمن '{ADMIN_USERNAME}' تلقائيًا من Environment Variables")
        else:
            admin_user.is_admin = True
            admin_user.set_password(ADMIN_PASSWORD)
            log.info(f"تم تحديث حساب الأدمن '{ADMIN_USERNAME}' وتأكيد صلاحياته")
        db.session.commit()

    if MOD_USERNAME and MOD_PASSWORD:
        mod_user = User.query.filter_by(username=MOD_USERNAME).first()
        if not mod_user:
            mod_user = User(
                username=MOD_USERNAME,
                telegram_username=MOD_TELEGRAM,
                account_id=generate_account_id(),
                is_mod=True,
            )
            mod_user.set_password(MOD_PASSWORD)
            db.session.add(mod_user)
            log.info(f"تم إنشاء حساب المشرف '{MOD_USERNAME}' تلقائيًا من Environment Variables")
        else:
            mod_user.is_mod = True
            mod_user.set_password(MOD_PASSWORD)
            log.info(f"تم تحديث حساب المشرف '{MOD_USERNAME}' وتأكيد صلاحياته")
        db.session.commit()

    if not Vault.query.get(1):
        db.session.add(Vault(id=1, last_balance=0))
        db.session.commit()

    # مرة واحدة بس مع هذا التحديث: نلغي كل أوامر البيع المفتوحة القديمة (بداية نظيفة لسوق التداول)
    if not MigrationFlag.query.get("purge_open_sell_orders_v1_5"):
        cancelled_count = Order.query.filter_by(side="sell", status="open").update({"status": "cancelled"})
        db.session.add(MigrationFlag(key="purge_open_sell_orders_v1_5"))
        db.session.commit()
        if cancelled_count:
            log.info(f"تم إلغاء {cancelled_count} أمر بيع مفتوح كبداية نظيفة مع هذا التحديث")

    # الأدمن والمشرف ممنوعين من التوثيق أصلاً - نتأكد إن أي حساب أدمن/مشرف قديم موثّق (زي أي تجربة سابقة) يترجع مش موثّق
    reset_count = User.query.filter(
        (User.is_admin.is_(True)) | (User.is_mod.is_(True))
    ).filter(User.telegram_verified.is_(True)).update(
        {"telegram_verified": False, "telegram_chat_id": None, "telegram_verify_code": None},
        synchronize_session=False,
    )
    if reset_count:
        db.session.commit()
        log.info(f"تم إلغاء توثيق {reset_count} حساب أدمن/مشرف (التوثيق ممنوع عليهم)")

# مراقبة الخزنة كل دقيقة (تحتاج WEB_CONCURRENCY=1 على Render عشان متتكررش)
scheduler = BackgroundScheduler()
scheduler.add_job(check_vault_deposits, "interval", minutes=1)
scheduler.add_job(process_matured_investments, "interval", minutes=1)
scheduler.add_job(process_loan_due_dates, "interval", minutes=15)
scheduler.add_job(apply_market_pressure_pricing, "interval", minutes=MARKET_PRESSURE_INTERVAL_MINUTES)
scheduler.start()

if __name__ == "__main__":
    app.run(debug=True)
