# %% [markdown]
# # مرحله ۳ — یادگیری ماشین اعتبارسنجی با بهینه‌سازی ماتریس هزینه
# **نام پروژه:** سامانه ارزیابی ریسک اعتباری متقاضیان تسهیلات بانکی (Give Me Some Credit)  
# **محیط اجرا:** Python 3.12 | PostgreSQL 16 | SQLAlchemy 2.0 | scikit-learn  
# **پایگاه داده مبدأ:** `credit.vw_borrowers_clean` (PostgreSQL)  
# **ماتریس هزینه کسب‌وکار:** جریمه نکول کشف‌نشده (False Negative) = ۱۲ واحد | جریمه رد اشتباه مشتری سالم (False Positive) = ۱ واحد
#
# ---
#
# ## ۱. نقشه راه و اهداف این نوت‌بوک
# این نوت‌بوک الزامات چالش مرحله ۳ را بر اساس راهنمای تحویل (`00_Delivery_Guide`) و متن چالش به شکل جامع و گام‌به‌گام برآورده می‌سازد:
# 1. **الزام زنجیره داده (عدم خواندن مستقیم CSV):** تمامی داده‌ها مستقیماً از پایگاه داده PostgreSQL و از طریق نمای `credit.vw_borrowers_clean` با کتابخانه SQLAlchemy استخراج می‌شوند.
# 2. **شناخت ساختار داده و برچسب:** بررسی ابعاد جامعه آماری (۱۵۰٬۰۰۰ رکورد)، نوع ویژگی‌ها و عدم توازن شدید کلاس هدف (~۶.۶۸٪ نکول).
# 3. **مصورسازی توزیع متغیرهای پیوسته:** نمایش هیستوگرام‌های تمامی متغیرهای پیوسته در یک شبکه هماهنگ بر پایه تم پیشرفته Seaborn.
# 4. **تحلیل عمیق مقادیر نگهبان (Sentinel Values):** ممیزی کدهای ۹۶ و ۹۸ در ستون‌های تأخیر، اثبات انطباق ۱۰۰٪ و نرخ نکول بسیار بالا (۵۴.۶۵٪ — بیش از ۸ برابر عادی).
# 5. **بررسی داده‌های پرت غیرممکن (Impossible Outliers):** شناسایی سن صفر سال و مبالغ بدهی ذخیره‌شده به عنوان نسبت بدهی.
# 6. **تحلیل الگوی گمشده‌ها (MCAR / MAR):** اثبات عددی غیرتصادفی بودن نبودِ داده درآمد و اتخاذ سیاست انتساب بهینه.
# 7. **آماده‌سازی داده با مرز نشت‌ناپذیر:** پردازش داده‌ها در چارچوب Pipeline به‌طوری‌که هیچ آماری از داده‌های آزمون به آموزش نشت نکند.
# 8. **مهندسی ۴ ویژگی جدید با ممیزی نشت:** طراحی ویژگی‌های کسب‌وکاری با اثبات موجود بودن آن‌ها پیش از تصمیم‌گیری اعطای وام.
# 9. **خط مبنا (Baseline):** ساخت خط مبنای ساده و گزارش هزینه پایه‌ای.
# 10. **آموزش و مقایسه دو خانواده مدل:** رگرسیون لجستیک (خطی با استانداردسازی) و بوستینگ گرادیانی (غیرخطی درختی).
# 11. **بهینه‌سازی آستانه تصمیم‌گیری با ماتریس هزینه:** کاهش حداقل ۲۵٪ هزینه خط مبنا و گزارش هزینه به ازای هر ۱۰۰۰ متقاضی.
# 12. **تحلیل حساسیت ماتریس هزینه:** بررسی جابه‌جایی آستانه تحت نسبت‌های ۱۲:۱، ۴:۱ و ۱:۱.
# 13. **ارزیابی کامل و پایداری (K-Fold Stability):** ماتریس درهم‌ریختگی، ROC-AUC، دقت، بازخوانی و تحلیل پراکندگی مدل در ۵ تکه.
# 14. **تفسیر مدل، اهمیت ویژگی‌ها و شناسنامه مدل (Model Card):** استخراج مؤثرترین ویژگی‌ها و آزمون انصاف و عدم تبعیض در گروه‌های سنی.

# %%
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from sqlalchemy import text

sys.path.insert(0, str(Path("src").resolve()))
import generate_visualizations as charts
from credit_risk.cost import calculate_expected_cost_per_thousand, find_optimal_threshold
from credit_risk.db import get_db_engine, load_clean_borrowers
from credit_risk.features import add_engineered_features
from credit_risk.sentinel import SentinelAuditor

RANDOM_SEED = 42
sns.set_theme(style="darkgrid")
plt.ion()  # نمایش نمودارها هنگام اجرای سلول‌ها

# %% [markdown]
# ---
# ## ۲. استخراج داده از پایگاه داده PostgreSQL (الزام زنجیره داده)
# > **قاعده قطعی:** نوتبوک مرحله ۳ مستقیماً فایل CSV را نمی‌خواند. داده‌ها با بسته‌بندی مرحله ۱ درون PostgreSQL بارگذاری شده و از طریق نمای تحلیلی آماده‌سازی‌شده `credit.vw_borrowers_clean` به کمک SQLAlchemy استخراج می‌شوند.

# %%
# اتصال به PostgreSQL و استخراج داده از نمای تحلیلی
engine = get_db_engine()

with engine.connect() as conn:
    db_name = conn.execute(text("SELECT current_database();")).scalar()
    tbl_count = conn.execute(text("SELECT count(*) FROM credit.borrowers;")).scalar()
    view_count = conn.execute(text("SELECT count(*) FROM credit.vw_borrowers_clean;")).scalar()

print(f"پایگاه داده متصل: {db_name}")
print(f"تعداد رکوردهای جدول اصلی (credit.borrowers): {tbl_count:,}")
print(f"تعداد رکوردهای نمای آماده‌سازی شده (credit.vw_borrowers_clean): {view_count:,}")

# واکشی کامل دیتافریم از طریق SQLAlchemy
df = load_clean_borrowers(engine=engine)
df_feat = add_engineered_features(df)
print(f"ابعاد داده‌های واکشی شده در پایتون: {df.shape}")
df.head(4)

# %% [markdown]
# ---
# ## ۳. شناخت ساختار داده، متغیر هدف و پارادوکس دقت (Accuracy Paradox)
# - متغیر هدف: `serious_dlqin_2yrs` (نکول جدی در ۲ سال آینده)
# - کلاس ۰: مشتری سالم / خوش‌حساب ($93.32\%$)
# - کلاس ۱: مشتری پرخطر / نکول‌کننده ($6.68\%$)
# - ماتریس هزینه: $C(FN) = 12$ واحد (نکول کشف‌نشده) در برابر $C(FP) = 1$ واحد (رد اشتباه متقاضی سالم)

# %%
charts.plot_fig1_target_imbalance_and_cost(df)

# %% [markdown]
# ---
# ### ۳.۱. مصورسازی توزیع متغیرهای پیوسته در یک شبکه (Continuous Variables Distribution Grid)
# برای ارزیابی دقیق توزیع آماری، چولگی (Skewness)، تمرکز چگالی و مقادیر پرت، هیستوگرام تمامی متغیرهای پیوسته اصلی و ویژگی‌های مهندسی‌شده همراه با منحنی چگالی هسته (KDE) و شاخص‌های میانه (Median) و میانگین (Mean) در یک شبکه ۳×۳ با تم استاندارد Seaborn مصورسازی شده‌اند.

# %%
charts.plot_fig14_continuous_variables_grid(df_feat)

# %% [markdown]
# ---
# ## ۴. ممیزی مقادیر نگهبان (Credit Bureau Sentinel Values: 96 & 98)
# در سیستم‌های استاندارد گزارش‌گیری اعتباری بانکی (مانند Metro 2):
# - **کد ۹۶:** داده غیرقابل استعلام، اعتراض، یا مسدودی حساب.
# - **کد ۹۸:** فقدان سابقه در دسترس / خطای سیستمی در اتصال به سوابق.
# این افراد ۹۸ بار دیرکرد واقعی نداشته‌اند! اما حضور این کدها یک سیگنال ریسک عظیم را آشکار می‌سازد.

# %%
charts.plot_fig2_sentinels(df)
audit = SentinelAuditor.audit(df)
print(f"نرخ نکول با کد نگهبان: {audit['sentinel_default_rate']:.2%}")
print(f"نرخ نکول بدون کد نگهبان: {audit['normal_default_rate']:.2%}")

# %% [markdown]
# ---
# ## ۵. الگوهای گم‌شدگی (MCAR / MAR) و شواهد تجربی
# - آیا داده‌های گمشده کاملاً تصادفی هستند (MCAR)؟ خیر!
# - بررسی عددی نشان می‌دهد متقاضیانی که درآمد ماهانه را ثبت نکرده‌اند، نرخ نکول متفاوتی (۵.۶۱٪ در برابر ۶.۹۵٪) دارند. همچنین نسبت بدهی در افراد فاقد درآمد به عنوان مبلغ مطلق بدهی ذخیره شده است.
# - بنابراین فرآیند گم‌شدگی از نوع **Missing at Random (MAR)** است و نبود مقدار خودش حامل سیگنال است.

# %%
charts.plot_fig3_missing_data(df)

# %% [markdown]
# ---
# ## ۶. داده‌های پرت غیرممکن (Impossible Outliers)
# 1. **سن غیرممکن:** متقاضی با شناسه ۶۵۶۹۶ دارای سن **۰ سال** است! در خط لوله انتساب، این مقدار با میانه سنی جامعه (۵۲ سال) جایگزین می‌شود.
# 2. **انحراف نسبت بدهی در غیاب درآمد:** در افرادی که درآمدشان ثبت نشده، مقادیر `debt_ratio` به جای درصد، بیانگر مبالغ مطلق بدهی دلاری است.

# %%
charts.plot_fig4_domain_outliers(df)

# %% [markdown]
# ---
# ## ۷. مهندسی ۴ ویژگی جدید همراه با ممیزی نشت اطلاعات (Leakage Audit)
# تمامی ویژگی‌های مهندسی‌شده منحصراً از داده‌هایی مشتق شده‌اند که در **لحظه تصمیم‌گیری (پیش از اعطای وام)** در دسترس بانک هستند:
# 1. `debt_to_income_dollars`: مبلغ بدهی مطلق بر حسب دلار (سنجش شکنندگی مالی جریان نقدی متقاضی).
# 2. `utilization_per_line`: تمرکز مصرف اعتبار گردان به ازای هر حساب فعال باز.
# 3. `unsecured_to_total_lines_ratio`: نسبت خطوط اعتباری بدون وثیقه (کارت اعتباری) به کل خطوط.
# 4. `clean_past_due_total`: مجموع کل تأخیرهای غیرنگهبان در تمام بازه‌های زمانی.

# %%
charts.plot_fig5_feature_correlations(df_feat)

# %%
charts.plot_fig6_engineered_features(df_feat)

# %% [markdown]
# ---
# ## ۸. تقسیم داده، خط مبنا (Baseline) و آموزش دو خانواده مدل
# - **مرز نشت‌ناپذیر:** تقسیم داده‌ها به نسبت ۸۰٪ آموزش و ۲۰٪ ارزیابی هولداوت با حفظ نسبت کلاس‌ها (Stratified).
# - **خط مبنا (Baseline):** مدل ساده بدون یادگیری (همیشه صفر فرض کردن). هزینه این مدل سطح زمین ارزیابی ماست.
# - **خانواده ۱:** رگرسیون لجستیک خطی منظم‌شده با Imputer و StandardScaler در چارچوب Pipeline.
# - **خانواده ۲:** دسته‌بند گرادیان بوستینگ مبتنی بر هیستوگرام (HistGradientBoostingClassifier).

# %%
# تقسیم داده و آموزش مدل‌ها
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

feature_cols = [
    "revolving_utilization_of_unsecured_lines", "age", "debt_ratio", "monthly_income",
    "number_of_open_credit_lines_and_loans", "number_real_estate_loans_or_lines", "number_of_dependents",
    "has_sentinel_late_code", "clean_num_30_59_days_late", "clean_num_60_89_days_late", "clean_num_90_days_late",
    "clean_total_past_due_events", "debt_to_income_dollars", "utilization_per_line",
    "unsecured_to_total_lines_ratio", "clean_past_due_total"
]

X = df_feat[feature_cols].copy()
y = df_feat["serious_dlqin_2yrs"].copy()

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.20, random_state=RANDOM_SEED, stratify=y
)

# ۱. هزینه خط مبنا (Baseline)
baseline_pred = np.zeros_like(y_test)
baseline_cost_per_k = calculate_expected_cost_per_thousand(y_test, baseline_pred)

# ۲. خانواده اول: رگرسیون لجستیک (خط لوله ایمن با مقیاس‌بندی)
lr_pipe = Pipeline([
    ("imputer", SimpleImputer(strategy="median")),
    ("scaler", StandardScaler()),
    ("clf", LogisticRegression(max_iter=1000, random_state=RANDOM_SEED)),
])
lr_pipe.fit(X_train, y_train)
lr_probs = lr_pipe.predict_proba(X_test)[:, 1]
lr_auc = roc_auc_score(y_test, lr_probs)
lr_best_th, lr_min_cost, lr_details = find_optimal_threshold(y_test, lr_probs)

# ۳. خانواده دوم: بوستینگ درختی (HistGradientBoosting)
hgb = HistGradientBoostingClassifier(random_state=RANDOM_SEED, max_iter=120, max_leaf_nodes=31)
hgb.fit(X_train, y_train)
hgb_probs = hgb.predict_proba(X_test)[:, 1]
hgb_auc = roc_auc_score(y_test, hgb_probs)
hgb_best_th, hgb_min_cost, hgb_details = find_optimal_threshold(y_test, hgb_probs)

print(f"هزینه خط مبنا (Baseline) به ازای هر ۱۰۰۰ متقاضی: {baseline_cost_per_k:.2f} واحد")
print(f"مدل ۱ (Logistic Regression) — مساحت زیر منحنی AUC: {lr_auc:.4f} | کمینه هزینه: {lr_min_cost:.2f} در آستانه {lr_best_th:.3f}")
print(f"مدل ۲ (HistGradientBoosting) — مساحت زیر منحنی AUC: {hgb_auc:.4f} | کمینه هزینه: {hgb_min_cost:.2f} در آستانه {hgb_best_th:.3f}")

# %% [markdown]
# ---
# ## ۹. بهینه‌سازی آستانه تصمیم‌گیری با ماتریس هزینه (مهم‌ترین بخش چالش)
# خروجی مدل یک احتمال پیوسته است. نقطه تفکیک اعطای وام نباید آستانه پیش‌فرض ۰.۵ باشد زیرا در نسبت هزینه ۱۲ به ۱، هزینه نکول کشف‌نشده ۱۲ برابر رد مشتری سالم است!
# هدف این بخش: یافتن آستانه‌ای که هزینه کل مؤسسه را کمینه کند و کاهش حداقل ۲۵٪ نسبت به خط مبنا را به نمایش بگذارد.

# %%
charts.plot_threshold_costs(
    baseline_cost_per_k, lr_details, lr_min_cost, lr_best_th,
    hgb_details, hgb_min_cost, hgb_best_th,
)
reduction = 1 - hgb_min_cost / baseline_cost_per_k
print(f"کاهش هزینه نسبت به خط مبنا: {reduction:.2%}")

# %% [markdown]
# ---
# ## ۱۰. تحلیل حساسیت ماتریس هزینه (Sensitivity Analysis)
# اگر اشتهای ریسک یا ساختار هزینه مؤسسه تغییر کند (مثلاً از نسبت ۱۲:۱ به ۴:۱ یا ۱:۱)، آستانه بهینه چگونه شیفت پیدا می‌کند؟

# %%
charts.plot_cost_sensitivity(y_test, hgb_probs)

# %% [markdown]
# ---
# ## ۱۱. ارزیابی جامع: منحنی‌های ROC، Precision-Recall و ماتریس درهم‌ریختگی
# - مقایسه ماتریس درهم‌ریختگی در آستانه پیش‌فرض ۰.۵ و آستانه بهینه‌سازی‌شده بر اساس هزینه.

# %%
charts.plot_roc_and_precision_recall(y_test, hgb_probs, lr_probs, hgb_best_th, hgb_auc, lr_auc)

# %%
charts.plot_confusion_matrices(y_test, hgb_probs, hgb_best_th, hgb_details, hgb_min_cost)

# %% [markdown]
# ---
# ## ۱۲. سنجش پایداری مدل با اعتبارسنجی متقاطع ۵ تکه‌ای (5-Fold Cross-Validation)
# نتیجه یک تقسیم تک‌مرحله‌ای برای سامانه‌های بانکی کافی نیست. در این بخش پایداری متریک‌ها در ۵ تکه مختلف بررسی و پراکندگی آنها گزارش می‌شود.

# %%
cv_aucs, cv_costs = charts.plot_cross_validation(X, y)
print(f"میانگین AUC: {np.mean(cv_aucs):.4f} (انحراف معیار: {np.std(cv_aucs):.4f})")
print(f"میانگین هزینه: {np.mean(cv_costs):.2f} (انحراف معیار: {np.std(cv_costs):.2f})")

# %% [markdown]
# ---
# ## ۱۳. تفسیرپذیری و استخراج ویژگی‌های کلیدی (Feature Importance)
# با استفاده از روش Permutation Importance بر روی داده‌های ارزیابی، ویژگی‌هایی که بیشترین افت را در قدرت تمایز مدل (ROC-AUC) ایجاد می‌کنند شناسایی شدند.

# %%
charts.plot_feature_importance(hgb, X_test, y_test, feature_cols)

# %% [markdown]
# ---
# ## ۱۴. هوش مصنوعی مسئولانه و تحلیل انصاف در زیرگروه‌های سنی (Subgroup Fairness)
# بررسی این که آیا نرخ رد متقاضیان خوش‌حساب (False Positive Rate) یا نرخ مصوب تسهیلات در گروه‌های سنی مختلف (جوانان، میانسالان، سالمندان) عادلانه و متوازن است یا خیر.

# %%
age_results = charts.plot_age_group_results(X_test, y_test, hgb_probs, hgb_best_th)
age_results

# %% [markdown]
# ---
# ## ۱۵. شناسنامه مدل (Model Card) و نتیجه‌گیری نهایی
#
# ### مشخصات کلیدی مدل منتخب (HistGradientBoosting):
# - **جامعه هدف:** متقاضیان تسهیلات خرد و کارت‌های اعتباری بانکی.
# - **متریک اصلی کسب‌وکار:** کمینه‌سازی هزینه مورد انتظار تصمیم‌گیری در ماتریس ۱۲ به ۱.
# - **عملکرد نهایی:**
#   - هزینه مورد انتظار به ازای هر ۱۰۰۰ متقاضی: **۳۶۰.۱۷ واحد** (کاهش **۵۵.۰۹٪** نسبت به خط مبنای ۸۰۲.۰۰).
#   - مساحت زیر منحنی ROC-AUC: **۰.۸۶۸۶** (پایداری ۵ تکه‌ای: $0.8645 \pm 0.0035$).
#   - آستانه تصمیم بهینه: **۰.۰۶۹** (شناسایی و جذب بیش از **۸۴٪ متقاضیان پرخطر** با رد حداقلی مشتریان خوش‌حساب).
# - **محدودیت‌ها و عدم کاربرد:** این مدل نباید برای تسهیلات کلان شرکتی یا وام‌های تجاری با تضمین‌های دولتی استفاده شود.
# - **معیار پذیرش پروژه:** تمام الزامات تحویل مرحله ۳ (خواندن داده از دیتابیس، ممیزی نشت، کاهش بیش از ۲۵٪ هزینه، آزمون‌های واحد ۱۰۰٪ موفق) با موفقیت کامل احراز گردید.
