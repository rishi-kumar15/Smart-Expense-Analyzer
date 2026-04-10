from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Expense, Budget
from datetime import datetime, date, timedelta
from functools import wraps
import os
import calendar

app = Flask(__name__)
app.config['SECRET_KEY'] = 'smart_expense_secret_2024_college_project'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///smart_expense.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

@app.context_processor
def inject_now():
    return {'now': datetime.now()}

# ─── Auto-categorization keyword map ──────────────────────────────────────────
CATEGORY_KEYWORDS = {
    'Food':          ['food','lunch','dinner','breakfast','restaurant','cafe','pizza','burger',
                      'snack','coffee','tea','grocery','groceries','swiggy','zomato','meal','eat','tiffin','canteen'],
    'Transport':     ['transport','taxi','uber','ola','bus','train','petrol','fuel','auto','metro',
                      'cab','flight','travel','ticket','fare','bike','rickshaw','rapido'],
    'Shopping':      ['shopping','amazon','flipkart','clothes','shirt','shoes','bag','mall',
                      'purchase','buy','fashion','dress','jeans','jacket','myntra','meesho'],
    'Health':        ['health','medicine','doctor','hospital','pharmacy','medical','clinic',
                      'gym','fitness','tablet','prescription','test','lab','apollo','dental'],
    'Entertainment': ['movie','cinema','netflix','spotify','game','party','fun','show',
                      'concert','theatre','amazon prime','hotstar','outing','trip','tour'],
    'Bills':         ['bill','electricity','water','wifi','internet','mobile','recharge','rent',
                      'emi','insurance','subscription','gas','maintenance','phone','broadband'],
    'Education':     ['college','school','fees','book','tuition','course','exam','library',
                      'stationery','pen','notebook','study','class','coaching'],
}

def auto_categorize(description: str) -> str:
    desc_lower = description.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                return category
    return 'Other'

# ─── Auth decorator ────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ─── Helper: get current user ─────────────────────────────────────────────────
def current_user():
    return User.query.get(session['user_id'])

# ─── Helper: monthly spending per category ────────────────────────────────────
def get_monthly_category_spending(user_id, year, month):
    from sqlalchemy import extract, func
    results = (db.session.query(Expense.category, func.sum(Expense.amount))
               .filter(Expense.user_id == user_id,
                       extract('year', Expense.date) == year,
                       extract('month', Expense.date) == month)
               .group_by(Expense.category).all())
    return {cat: round(float(amt or 0), 2) for cat, amt in results}

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

# ── Register ──────────────────────────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')

        if not username or not email or not password:
            flash('All fields are required.', 'danger')
        elif password != confirm:
            flash('Passwords do not match.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('Username already taken.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
        else:
            user = User(username=username, email=email,
                        password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

# ── Login ─────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id']   = user.id
            session['username']  = user.username
            flash(f'Welcome back, {user.username}! 👋', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

# ── Logout ────────────────────────────────────────────────────────────────────
@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    user  = current_user()
    today = date.today()
    year, month = today.year, today.month

    # All expenses this month
    monthly_expenses = Expense.query.filter(
        Expense.user_id == user.id,
        db.extract('year',  Expense.date) == year,
        db.extract('month', Expense.date) == month
    ).order_by(Expense.date.desc()).all()

    # Summary
    total_all    = round(sum(float(e.amount) for e in Expense.query.filter_by(user_id=user.id).all()), 2)
    total_month  = round(sum(float(e.amount) for e in monthly_expenses), 2)
    category_map = get_monthly_category_spending(user.id, year, month)

    top_cat = max(category_map, key=category_map.get) if category_map else 'N/A'

    # Budget alerts
    budgets     = Budget.query.filter_by(user_id=user.id).all()
    alert_count = sum(1 for b in budgets if category_map.get(b.category, 0) > b.monthly_limit)

    # Last 6 months for bar chart
    monthly_labels, monthly_totals = [], []
    for i in range(5, -1, -1):
        d = today.replace(day=1) - timedelta(days=i * 28)
        label = d.strftime('%b %Y')
        total = float(db.session.query(db.func.sum(Expense.amount)).filter(
            Expense.user_id == user.id,
            db.extract('year', Expense.date)  == d.year,
            db.extract('month', Expense.date) == d.month
        ).scalar() or 0)
        monthly_labels.append(label)
        monthly_totals.append(round(total, 2))

    recent = monthly_expenses[:8]

    return render_template('dashboard.html',
        user=user,
        total_all=total_all,
        total_month=total_month,
        top_cat=top_cat,
        alert_count=alert_count,
        category_map=category_map,
        monthly_labels=monthly_labels,
        monthly_totals=monthly_totals,
        recent=recent,
        today=today
    )

# ── Add Expense ───────────────────────────────────────────────────────────────
@app.route('/add-expense', methods=['GET', 'POST'])
@login_required
def add_expense():
    user = current_user()
    categories = list(CATEGORY_KEYWORDS.keys()) + ['Other']
    if request.method == 'POST':
        amount      = request.form.get('amount')
        description = request.form.get('description', '').strip()
        category    = request.form.get('category', '').strip()
        exp_date    = request.form.get('date')
        note        = request.form.get('note', '').strip()

        if not amount or not description or not exp_date:
            flash('Amount, Description and Date are required.', 'danger')
        else:
            # Auto-categorize if "Auto" selected
            if category == 'Auto' or not category:
                category = auto_categorize(description)

            expense = Expense(
                user_id=user.id,
                amount=float(amount),
                description=description,
                category=category,
                date=datetime.strptime(exp_date, '%Y-%m-%d').date(),
                note=note
            )
            db.session.add(expense)
            db.session.commit()
            flash(f'Expense added! Auto-categorized as <strong>{category}</strong>.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('add_expense.html', user=user, categories=categories, today=date.today().isoformat())

# ── Edit Expense ──────────────────────────────────────────────────────────────
@app.route('/edit-expense/<int:expense_id>', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    user    = current_user()
    expense = Expense.query.filter_by(id=expense_id, user_id=user.id).first_or_404()
    categories = list(CATEGORY_KEYWORDS.keys()) + ['Other']
    if request.method == 'POST':
        expense.amount      = float(request.form.get('amount', expense.amount))
        expense.description = request.form.get('description', expense.description).strip()
        expense.category    = request.form.get('category', expense.category)
        expense.date        = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        expense.note        = request.form.get('note', '').strip()
        db.session.commit()
        flash('Expense updated successfully.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('add_expense.html', user=user, expense=expense, categories=categories,
                           today=date.today().isoformat(), edit=True)

# ── Delete Expense ────────────────────────────────────────────────────────────
@app.route('/delete-expense/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    user    = current_user()
    expense = Expense.query.filter_by(id=expense_id, user_id=user.id).first_or_404()
    db.session.delete(expense)
    db.session.commit()
    flash('Expense deleted.', 'info')
    return redirect(request.referrer or url_for('dashboard'))

# ── Reports ───────────────────────────────────────────────────────────────────
@app.route('/reports')
@login_required
def reports():
    user  = current_user()
    today = date.today()

    start_str = request.args.get('start', today.replace(day=1).isoformat())
    end_str   = request.args.get('end',   today.isoformat())
    start_dt  = datetime.strptime(start_str, '%Y-%m-%d').date()
    end_dt    = datetime.strptime(end_str,   '%Y-%m-%d').date()

    expenses = Expense.query.filter(
        Expense.user_id == user.id,
        Expense.date >= start_dt,
        Expense.date <= end_dt
    ).order_by(Expense.date.desc()).all()

    # Category totals
    cat_totals = {}
    for e in expenses:
        cat_totals[e.category] = round(cat_totals.get(e.category, 0) + float(e.amount), 2)
    total = round(sum(float(e.amount) for e in expenses), 2)

    return render_template('reports.html', user=user, expenses=expenses,
                           cat_totals=cat_totals, total=total,
                           start=start_str, end=end_str)

# ── Budget ────────────────────────────────────────────────────────────────────
@app.route('/budget', methods=['GET', 'POST'])
@login_required
def budget():
    user       = current_user()
    today      = date.today()
    categories = list(CATEGORY_KEYWORDS.keys()) + ['Other']

    if request.method == 'POST':
        # ── 1. Save the overall monthly limit ──────────────────────
        overall_val = request.form.get('overall_limit', '').strip()
        if overall_val:
            try:
                overall_f = max(0.0, float(overall_val))
                total_bud = Budget.query.filter_by(user_id=user.id, category='_total_').first()
                if total_bud:
                    total_bud.monthly_limit = overall_f
                else:
                    db.session.add(Budget(user_id=user.id, category='_total_', monthly_limit=overall_f))
            except ValueError:
                pass

        # ── 2. Save per-category limits ────────────────────────────
        for cat in categories:
            limit_val = request.form.get(f'limit_{cat}', '').strip()
            if limit_val:
                try:
                    limit_f = float(limit_val)
                    if limit_f < 0:
                        continue
                    existing = Budget.query.filter_by(user_id=user.id, category=cat).first()
                    if existing:
                        existing.monthly_limit = limit_f
                    else:
                        db.session.add(Budget(user_id=user.id, category=cat, monthly_limit=limit_f))
                except ValueError:
                    pass

        db.session.commit()
        flash('Budget saved successfully! 🎯', 'success')
        return redirect(url_for('budget'))

    # ── Fetch overall limit ────────────────────────────────────────
    total_bud   = Budget.query.filter_by(user_id=user.id, category='_total_').first()
    total_limit = float(total_bud.monthly_limit) if total_bud else 0.0

    # ── Budget vs actual spending this month ───────────────────────
    spending    = get_monthly_category_spending(user.id, today.year, today.month)
    total_spent = round(sum(spending.values()), 2)
    budgets     = {b.category: b for b in Budget.query.filter_by(user_id=user.id).all()}

    budget_data = []
    for cat in categories:
        b       = budgets.get(cat)
        limit   = float(b.monthly_limit) if b else 0.0
        spent   = spending.get(cat, 0)
        percent = min(round((spent / limit) * 100), 100) if limit > 0 else 0
        status  = 'over' if (limit > 0 and spent > limit) else ('warning' if percent >= 80 else 'ok')
        budget_data.append({
            'id': b.id if b else None,
            'category': cat,
            'limit': limit,
            'spent': spent,
            'percent': percent,
            'status': status
        })

    # Overall % used against total limit
    total_percent = min(round((total_spent / total_limit) * 100), 100) if total_limit > 0 else 0
    total_status  = 'over' if (total_limit > 0 and total_spent > total_limit) else (
                    'warning' if total_percent >= 80 else 'ok')

    return render_template('budget.html', user=user, budget_data=budget_data,
                           categories=categories, spending=spending,
                           total_limit=total_limit, total_spent=total_spent,
                           total_percent=total_percent, total_status=total_status)

# ── Delete Budget ─────────────────────────────────────────────────────────────
@app.route('/delete-budget/<int:budget_id>', methods=['POST'])
@login_required
def delete_budget(budget_id):
    bud = Budget.query.filter_by(id=budget_id, user_id=session['user_id']).first_or_404()
    db.session.delete(bud)
    db.session.commit()
    flash('Budget removed.', 'info')
    return redirect(url_for('budget'))

# ── Import CSV ────────────────────────────────────────────────────────────────
@app.route('/import-csv', methods=['GET', 'POST'])
@login_required
def import_csv():
    user = current_user()
    if request.method == 'POST':
        f = request.files.get('csv_file')
        if not f or not f.filename.endswith('.csv'):
            flash('Please upload a valid .csv file.', 'danger')
            return redirect(url_for('import_csv'))
        import csv, io
        stream   = io.StringIO(f.stream.read().decode('utf-8-sig'), newline=None)
        reader   = csv.DictReader(stream)
        imported = 0
        errors   = 0
        for row in reader:
            try:
                desc  = (row.get('description') or row.get('Description') or '').strip()
                amt   = float(row.get('amount') or row.get('Amount') or 0)
                raw_d = (row.get('date') or row.get('Date') or '').strip()
                cat   = (row.get('category') or row.get('Category') or '').strip()
                note  = (row.get('note') or row.get('Note') or '').strip()
                if not desc or amt <= 0 or not raw_d:
                    errors += 1; continue
                for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y'):
                    try: exp_date = datetime.strptime(raw_d, fmt).date(); break
                    except: pass
                else: errors += 1; continue
                if not cat or cat not in (list(CATEGORY_KEYWORDS.keys()) + ['Other']):
                    cat = auto_categorize(desc)
                db.session.add(Expense(user_id=user.id, amount=amt, description=desc,
                                       category=cat, date=exp_date, note=note))
                imported += 1
            except Exception:
                errors += 1
        db.session.commit()
        flash(f'✅ Imported <strong>{imported}</strong> expenses. {"⚠️ " + str(errors) + " rows skipped." if errors else ""}', 'success')
        return redirect(url_for('dashboard'))
    return render_template('import_csv.html', user=user)

# ── Generate Sample Data ──────────────────────────────────────────────────────
@app.route('/generate-sample', methods=['POST'])
@login_required
def generate_sample():
    import random
    user  = current_user()
    today = date.today()
    samples = [
        ('Swiggy dinner',            'Food',          220),
        ('Zomato lunch',             'Food',          180),
        ('Restaurant breakfast',     'Food',          120),
        ('Grocery shopping',         'Food',          850),
        ('Coffee at cafe',           'Food',           90),
        ('Canteen snack',            'Food',           45),
        ('Uber to college',          'Transport',     350),
        ('Ola cab',                  'Transport',     280),
        ('Metro card recharge',      'Transport',     200),
        ('Petrol refill',            'Transport',     500),
        ('Bus pass',                 'Transport',     150),
        ('Amazon order',             'Shopping',     1200),
        ('Flipkart clothes',         'Shopping',      899),
        ('Mall shopping',            'Shopping',      640),
        ('Netflix subscription',     'Entertainment', 199),
        ('Movie tickets',            'Entertainment', 480),
        ('Spotify premium',          'Entertainment', 119),
        ('Electricity bill',         'Bills',         750),
        ('WiFi internet bill',       'Bills',         599),
        ('Mobile recharge',          'Bills',         299),
        ('Gym membership',           'Health',        999),
        ('Pharmacy medicine',        'Health',        320),
        ('Doctor consultation',      'Health',        500),
        ('College fees installment', 'Education',    5000),
        ('Textbooks purchase',       'Education',     650),
        ('Stationery',               'Education',     180),
    ]
    added = 0
    for i in range(30):
        desc, cat, base_amt = random.choice(samples)
        amt  = round(base_amt * random.uniform(0.85, 1.2), 2)
        days = random.randint(0, 59)   # spread over last 2 months
        exp_date = today - timedelta(days=days)
        db.session.add(Expense(user_id=user.id, amount=amt, description=desc,
                               category=cat, date=exp_date))
        added += 1
    db.session.commit()
    flash(f'🤖 Auto-generated <strong>{added}</strong> sample expenses across the last 2 months!', 'success')
    return redirect(url_for('dashboard'))

# ── Forecast ──────────────────────────────────────────────────────────────────
@app.route('/forecast')
@login_required
def forecast():
    user  = current_user()
    today = date.today()

    # Collect last 6 months of totals
    labels, actuals = [], []
    for i in range(5, -1, -1):
        d = (today.replace(day=1) - timedelta(days=i * 28))
        lbl   = d.strftime('%b %Y')
        total = float(db.session.query(db.func.sum(Expense.amount)).filter(
            Expense.user_id == user.id,
            db.extract('year',  Expense.date) == d.year,
            db.extract('month', Expense.date) == d.month
        ).scalar() or 0)
        labels.append(lbl)
        actuals.append(round(total, 2))

    # Simple linear trend forecast for next 3 months
    n = len(actuals)
    x_mean = (n - 1) / 2
    y_mean = sum(actuals) / n if n else 0
    if n > 1:
        numer = sum((i - x_mean) * (actuals[i] - y_mean) for i in range(n))
        denom = sum((i - x_mean) ** 2 for i in range(n))
        slope = numer / denom if denom else 0
    else:
        slope = 0

    forecast_vals = []
    for j in range(1, 4):
        predicted = max(0, round(y_mean + slope * (n - x_mean + j - 1), 2))
        forecast_vals.append(predicted)
        d_next = today.replace(day=1) + timedelta(days=j * 31)
        labels.append(d_next.strftime('%b %Y'))

    # Monthly category breakdown for last 6 months (for category trend chart)
    cat_trends = {cat: [] for cat in CATEGORY_KEYWORDS}
    cat_trends['Other'] = []
    for i in range(5, -1, -1):
        d   = (today.replace(day=1) - timedelta(days=i * 28))
        cm  = get_monthly_category_spending(user.id, d.year, d.month)
        for cat in cat_trends:
            cat_trends[cat].append(cm.get(cat, 0))

    return render_template('forecast.html', user=user,
                           labels=labels,
                           actuals=actuals + [None, None, None],
                           forecast_vals=[None] * 5 + [actuals[-1]] + forecast_vals,
                           slope=round(slope, 2),
                           avg=round(y_mean, 2),
                           cat_trends=cat_trends)

# ─── App entry point ──────────────────────────────────────────────────────────
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)
