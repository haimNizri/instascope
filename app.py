#!/usr/bin/env python3
"""
InstaScope — Instagram Profile Analyzer Web App
"""

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for, flash
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from functools import wraps

from config import Config
from models import (
    db, Account, FollowerSnapshot, FollowEvent,
    PlannedPost, PostData, Report, ScanLog, StoryViewer, User,
)

from analyzer import (
    analyze_authenticity,
    analyze_content_performance,
    analyze_content_studio,
    analyze_follow_relationship,
    analyze_follower_demographics,
    analyze_lurkers,
    analyze_unfollowers,
    business_insights,
    detect_campaigns,
    estimate_audience_age,
    estimate_demographics,
)
from scraper import (
    compare_follower_snapshots,
    get_loader,
    load_follower_snapshots,
    load_saved_session_id,
    load_story_viewer_history,
    login_with_session_id,
    save_follower_snapshot,
    save_session_id,
    scrape_followers,
    scrape_following,
    scrape_post_likers,
    scrape_posts,
    scrape_profile,
    scrape_story_viewers,
)

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = ""


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# Create/update tables on first run
with app.app_context():
    db.create_all()
    # Add missing columns if they don't exist (migration-lite)
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    if 'users' in inspector.get_table_names():
        existing = [c['name'] for c in inspector.get_columns('users')]
        with db.engine.connect() as conn:
            if 'subscription_tier' not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(16) DEFAULT 'free'"))
            if 'subscription_id' not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN subscription_id VARCHAR(128)"))
            if 'subscription_status' not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN subscription_status VARCHAR(32)"))
            if 'customer_portal_url' not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN customer_portal_url TEXT"))
            if 'trial_used' not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN trial_used JSON"))
            if 'instagram_verified' not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN instagram_verified BOOLEAN DEFAULT FALSE"))
            if 'trial_expires_at' not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN trial_expires_at TIMESTAMP"))
            if 'ai_generations_used' not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN ai_generations_used INTEGER DEFAULT 0"))
            if 'ai_reset_month' not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN ai_reset_month VARCHAR(7)"))
            conn.commit()


# ── Auth decorators ─────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


def ig_verified_required(f):
    """Decorator: ensures user has verified their Instagram account."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role == "admin":
            return f(*args, **kwargs)
        if not current_user.instagram_verified:
            flash("Please connect your Instagram account first using the Chrome extension.")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


def can_view_account(f):
    """Decorator: checks user can view the <username> in the URL."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "admin" and not current_user.instagram_verified:
            flash("Please connect your Instagram account first using the Chrome extension.")
            return redirect(url_for("index"))
        username = kwargs.get("username", "")
        if not current_user.can_view(username):
            flash("You don't have permission to view this account.")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


def api_can_view_account(f):
    """Decorator for API endpoints: checks auth + account permission."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        username = kwargs.get("username", "")
        if not current_user.can_view(username):
            return jsonify({"error": "Permission denied"}), 403
        return f(*args, **kwargs)
    return decorated


def pro_required(feature_name):
    """Decorator: checks if user can use a pro feature."""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated(*args, **kwargs):
            allowed, reason = current_user.can_use_feature(feature_name)
            if not allowed:
                return jsonify({"error": reason, "upgrade": True}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


OUTPUT_DIR = "output"


def get_ig_session_id():
    """Get Instagram session_id from DB (must be called with app context)."""
    try:
        account = Account.query.filter(Account.session_id.isnot(None)).order_by(Account.updated_at.desc()).first()
        if account and account.session_id:
            return account.session_id
    except Exception:
        pass
    return load_saved_session_id()


def validate_scan_username(username):
    """Validate that the current user is allowed to scan this username.
    Returns (ok, error_response) tuple."""
    if current_user.role == "admin":
        return True, None
    if not current_user.instagram_verified:
        return False, (jsonify({"error": "Connect your Instagram account first"}), 403)
    if not current_user.instagram_username:
        return False, (jsonify({"error": "No Instagram account linked"}), 403)
    if username.lower() != current_user.instagram_username.lower():
        return False, (jsonify({"error": "You can only scan your own account"}), 403)
    return True, None
HISTORY_FILE = Path(OUTPUT_DIR) / "history.json"
tasks = {}  # task_id -> {status, progress, result, error}


# ── History ──────────────────────────────────────────────────────────────────

def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []


def save_history(history):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, default=str)


def add_to_history(username, profile_data, auth):
    history = load_history()
    # Remove existing entry for this user
    history = [h for h in history if h["username"] != username]
    history.insert(0, {
        "username": username,
        "full_name": profile_data.get("full_name", ""),
        "followers": profile_data.get("followers", 0),
        "posts_count": profile_data.get("posts_count", 0),
        "is_verified": profile_data.get("is_verified", False),
        "authenticity_score": auth["authenticity_score"],
        "verdict": auth["verdict"],
        "profile_pic_url": profile_data.get("profile_pic_url", ""),
        "analyzed_at": datetime.now().isoformat(),
    })
    save_history(history)


# ── DB Helpers ───────────────────────────────────────────────────────────────

def db_get_or_create_account(username):
    """Get or create an account record."""
    account = Account.query.filter_by(username=username).first()
    if not account:
        account = Account(username=username)
        db.session.add(account)
        db.session.commit()
    return account


def db_save_report(username, report_type, data):
    """Save or update a report in the database."""
    account = db_get_or_create_account(username)
    # Update existing or create new
    report = Report.query.filter_by(account_id=account.id, report_type=report_type).first()
    if report:
        report.data = data
        report.created_at = datetime.utcnow()
    else:
        report = Report(account_id=account.id, report_type=report_type, data=data)
        db.session.add(report)
    db.session.commit()
    return report


def db_get_report(username, report_type):
    """Get the latest report from database."""
    account = Account.query.filter_by(username=username).first()
    if not account:
        return None
    report = Report.query.filter_by(
        account_id=account.id, report_type=report_type
    ).order_by(Report.created_at.desc()).first()
    return report.data if report else None


def db_save_snapshot(username, snapshot_type, count, usernames_dict):
    """Save a follower/following snapshot to DB."""
    account = db_get_or_create_account(username)
    snap = FollowerSnapshot(
        account_id=account.id,
        snapshot_type=snapshot_type,
        count=count,
        usernames=usernames_dict,
    )
    db.session.add(snap)
    db.session.commit()
    return snap


def db_save_follow_events(username, unfollowers, new_followers):
    """Record follow/unfollow events."""
    from analyzer import guess_gender
    account = db_get_or_create_account(username)
    for u in unfollowers:
        g = guess_gender(u.get("full_name", ""))
        event = FollowEvent(
            account_id=account.id, event_type="unfollowed",
            target_username=u["username"], target_full_name=u.get("full_name", ""),
            target_is_private=u.get("is_private"), target_is_verified=u.get("is_verified"),
            target_gender=g if g != "likely_female" else "female",
        )
        db.session.add(event)
    for u in new_followers:
        g = guess_gender(u.get("full_name", ""))
        event = FollowEvent(
            account_id=account.id, event_type="new_follower",
            target_username=u["username"], target_full_name=u.get("full_name", ""),
            target_is_private=u.get("is_private"), target_is_verified=u.get("is_verified"),
            target_gender=g if g != "likely_female" else "female",
        )
        db.session.add(event)
    db.session.commit()


def db_update_account_profile(username, profile_data):
    """Update account profile info in DB."""
    account = db_get_or_create_account(username)
    account.full_name = profile_data.get("full_name")
    account.biography = profile_data.get("biography")
    account.external_url = profile_data.get("external_url")
    account.followers_count = profile_data.get("followers", 0)
    account.following_count = profile_data.get("following", 0)
    account.posts_count = profile_data.get("posts_count", 0)
    account.is_private = profile_data.get("is_private", False)
    account.is_verified = profile_data.get("is_verified", False)
    account.profile_pic_url = profile_data.get("profile_pic_url")
    account.business_category = profile_data.get("business_category")
    account.updated_at = datetime.utcnow()
    db.session.commit()
    return account


# ── Background worker ────────────────────────────────────────────────────────

def run_analysis(task_id, username, post_limit=50, deep=False,
                 ig_user=None, ig_pass=None, session_id=None):
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass, session_id=session_id)

        tasks[task_id]["progress"] = "Loading profile..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        with open(Path(OUTPUT_DIR) / username / "profile.json") as f:
            profile_data = json.load(f)

        posts_data = []
        followers_sample = None

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            tasks[task_id]["progress"] = "Profile is private — limited analysis..."
        else:
            tasks[task_id]["progress"] = f"Fetching posts (up to {post_limit})..."
            posts_data = scrape_posts(
                L, profile_obj, OUTPUT_DIR,
                limit=post_limit, download_media=False
            )

            if deep:
                tasks[task_id]["progress"] = "Sampling followers for demographics..."
                sample = []
                try:
                    for i, follower in enumerate(profile_obj.get_followers()):
                        if i >= 200:
                            break
                        sample.append({
                            "username": follower.username,
                            "full_name": follower.full_name,
                            "is_private": follower.is_private,
                            "is_verified": follower.is_verified,
                        })
                        if (i + 1) % 50 == 0:
                            tasks[task_id]["progress"] = f"Sampled {i+1} followers..."
                except Exception:
                    pass
                if sample:
                    followers_sample = sample

        tasks[task_id]["progress"] = "Analyzing authenticity..."
        auth = analyze_authenticity(profile_data, posts_data, followers_sample)

        tasks[task_id]["progress"] = "Estimating audience..."
        age = estimate_audience_age(posts_data, profile_data)

        tasks[task_id]["progress"] = "Detecting campaigns..."
        campaigns = detect_campaigns(posts_data)

        tasks[task_id]["progress"] = "Generating business insights..."
        biz = business_insights(profile_data, posts_data)

        report = {
            "profile": profile_data,
            "authenticity": auth,
            "audience_age": age,
            "campaigns": campaigns,
            "business_insights": biz,
        }

        if followers_sample:
            report["demographics"] = estimate_demographics(followers_sample)

        # Save report
        report_path = Path(OUTPUT_DIR) / username / "analysis.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        # Persist to database (survives Render restarts)
        try:
            with app.app_context():
                db_save_report(username, 'analysis', report)
        except Exception:
            pass  # file save is the fallback

        add_to_history(username, profile_data, auth)

        tasks[task_id]["status"] = "done"
        tasks[task_id]["result"] = report

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)


# ── Auth Routes ──────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.")
            return render_template("login.html")
        if not user.is_active:
            flash("Your account is pending admin approval.")
            return render_template("login.html")
        login_user(user, remember=True)
        return redirect(request.args.get("next") or url_for("index"))
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        display_name = request.form.get("display_name", "").strip()
        ig_username = request.form.get("instagram_username", "").strip().lstrip("@")

        if not email or not password:
            flash("Email and password required.")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.")
            return render_template("register.html")
        if User.query.filter_by(email=email).first():
            flash("Email already registered.")
            return render_template("register.html")

        # First user becomes admin and auto-approved
        is_first = User.query.count() == 0
        user = User(
            email=email,
            display_name=display_name or email.split("@")[0],
            role="admin" if is_first else "user",
            is_active=True if is_first else False,
            instagram_username=ig_username,
            allowed_accounts=ig_username if ig_username else "",
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        if is_first:
            login_user(user, remember=True)
            flash("Welcome! You are the admin.")
            return redirect(url_for("index"))
        else:
            flash("Account created. Waiting for admin approval.")
            return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        new_password = request.form.get("new_password", "")
        admin_code = request.form.get("admin_code", "")

        user = User.query.filter_by(email=email).first()
        if not user:
            flash("No account found with that email.")
            return render_template("forgot_password.html")

        # Admin reset: admin can set a reset code in env var, or use default for first setup
        reset_code = os.environ.get("RESET_CODE", "instascope-reset-2026")
        if admin_code != reset_code:
            flash("Invalid reset code. Contact the admin for help.")
            return render_template("forgot_password.html")

        if len(new_password) < 6:
            flash("Password must be at least 6 characters.")
            return render_template("forgot_password.html")

        user.set_password(new_password)
        db.session.commit()
        flash("Password reset successfully. You can now log in.")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/connect")
@login_required
def connect_page():
    return render_template("connect.html")


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Admin Panel ──────────────────────────────────────────────────────────────

@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin.html", users=users)


@app.post("/api/admin/users/<int:user_id>")
@login_required
@admin_required
def admin_update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    data = request.json or {}
    if "is_active" in data:
        user.is_active = data["is_active"]
    if "role" in data and data["role"] in ("admin", "user"):
        user.role = data["role"]
    if "allowed_accounts" in data:
        user.allowed_accounts = data["allowed_accounts"]
    if "instagram_username" in data:
        user.instagram_username = data["instagram_username"]
    if "new_password" in data and len(data["new_password"]) >= 6:
        user.set_password(data["new_password"])
    if "subscription_tier" in data and data["subscription_tier"] in ("free", "pro", "creator"):
        user.subscription_tier = data["subscription_tier"]
        if data["subscription_tier"] == "pro":
            user.subscription_status = "active"
        else:
            user.subscription_status = None
    if "trial_days" in data:
        days = int(data["trial_days"])
        if days > 0:
            from datetime import timedelta
            user.trial_expires_at = datetime.utcnow() + timedelta(days=days)
        else:
            user.trial_expires_at = None
    db.session.commit()
    return jsonify({"ok": True, "user": user.to_dict()})


@app.delete("/api/admin/users/<int:user_id>")
@login_required
@admin_required
def admin_delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.id == current_user.id:
        return jsonify({"error": "Cannot delete yourself"}), 400
    db.session.delete(user)
    db.session.commit()
    return jsonify({"ok": True})


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if not current_user.is_authenticated:
        return render_template("landing.html")
    return render_template("index.html")


@app.route("/dashboard/<username>")
@can_view_account
def dashboard(username):
    return render_template("dashboard.html", username=username)


@app.route("/unfollowers/<username>")
@can_view_account
def unfollowers_page(username):
    return render_template("unfollowers.html", username=username)


@app.route("/lurkers/<username>")
@can_view_account
def lurkers_page(username):
    return render_template("lurkers.html", username=username)


@app.route("/relationships/<username>")
@can_view_account
def relationships_page(username):
    return render_template("relationships.html", username=username)


@app.route("/advisor/<username>")
@can_view_account
def advisor_page(username):
    return render_template("advisor.html", username=username)


@app.route("/studio/<username>")
@can_view_account
def studio_page(username):
    return render_template("studio.html", username=username)


@app.route("/planner")
@login_required
def planner_page():
    return render_template("planner.html")


@app.route("/insights/<username>")
@can_view_account
def insights_page(username):
    return render_template("insights.html", username=username)


# ── API ──────────────────────────────────────────────────────────────────────

@app.post("/api/analyze")
@login_required
def api_analyze():
    data = request.json or {}
    username = data.get("username", "").strip().lstrip("@")
    if not username:
        return jsonify({"error": "Username required"}), 400

    ok, err = validate_scan_username(username)
    if not ok:
        return err

    task_id = str(uuid.uuid4())[:8]
    post_limit = data.get("post_limit", 50)
    deep = data.get("deep", False)
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_analysis,
        args=(task_id, username, post_limit, deep, ig_user, ig_pass, get_ig_session_id()),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/status/<task_id>")
def api_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found", "lost": True}), 404
    return jsonify(task)


@app.get("/api/report/<username>")
@api_can_view_account
def api_report(username):
    # Try database first (survives Render restarts)
    db_data = db_get_report(username, 'analysis')
    if db_data:
        return jsonify(db_data)
    # Fall back to local file
    report_path = Path(OUTPUT_DIR) / username / "analysis.json"
    if not report_path.exists():
        return jsonify({"error": "No report found"}), 404
    with open(report_path) as f:
        return jsonify(json.load(f))


@app.get("/api/history")
@login_required
def api_history():
    return jsonify(load_history())


@app.delete("/api/history/<username>")
def api_delete_history(username):
    history = load_history()
    history = [h for h in history if h["username"] != username]
    save_history(history)
    return jsonify({"ok": True})


@app.post("/api/session")
def api_set_session():
    """Save Instagram sessionid. Works via logged-in user OR secret token for bookmarklet."""
    data = request.json or {}
    session_id = data.get("session_id", "").strip()
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    # Auth check: either logged in, or provide the app secret key
    token = data.get("token", "")
    if not current_user.is_authenticated:
        if token != app.config["SECRET_KEY"]:
            return jsonify({"error": "Login required or invalid token"}), 401

    # Verify it works
    import instaloader as _il
    L = _il.Instaloader()
    L.context._session.cookies.set(
        "sessionid", session_id, domain=".instagram.com", path="/"
    )
    ig_username = L.test_login()
    if not ig_username:
        return jsonify({"error": "Invalid or expired sessionid"}), 401

    # If logged-in user is not admin, verify the IG account matches their registration
    if current_user.is_authenticated and current_user.role != "admin":
        if current_user.instagram_username:
            if ig_username.lower() != current_user.instagram_username.lower():
                return jsonify({
                    "error": f"This Instagram session belongs to @{ig_username}, but your account is registered with @{current_user.instagram_username}. Please log into the correct Instagram account."
                }), 403
            # Mark as verified — this IS their account
            current_user.instagram_verified = True
            db.session.commit()

        # Auto-set instagram_username if not set yet during registration
        if not current_user.instagram_username:
            current_user.instagram_username = ig_username
            current_user.allowed_accounts = ig_username
            current_user.instagram_verified = True
            db.session.commit()

    # Save to file (local dev)
    try:
        save_session_id(session_id)
    except Exception:
        pass

    # Save to DB (cloud)
    account = db_get_or_create_account(ig_username)
    account.session_id = session_id
    db.session.commit()

    return jsonify({"ok": True, "username": ig_username})


# CORS preflight for bookmarklet cross-origin requests
@app.route("/api/session", methods=["OPTIONS"])
def api_session_options():
    resp = app.make_default_options_response()
    resp.headers["Access-Control-Allow-Origin"] = "https://www.instagram.com"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.after_request
def add_cors_for_session(response):
    """Add CORS headers for the session endpoint (bookmarklet needs it)."""
    if request.path == "/api/session":
        response.headers["Access-Control-Allow-Origin"] = "https://www.instagram.com"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.get("/api/session")
@login_required
def api_get_session():
    """Check if a saved session exists."""
    # Try DB first (cloud), then file (local)
    sid = None
    db_username = None

    accounts = Account.query.filter(Account.session_id.isnot(None)).order_by(Account.updated_at.desc()).first()
    if accounts and accounts.session_id:
        sid = accounts.session_id
        db_username = accounts.username

    if not sid:
        sid = load_saved_session_id()

    if not sid:
        return jsonify({"logged_in": False})

    # Quick verify
    import instaloader as _il
    L = _il.Instaloader()
    L.context._session.cookies.set(
        "sessionid", sid, domain=".instagram.com", path="/"
    )
    username = L.test_login()
    if username:
        return jsonify({"logged_in": True, "username": username})
    return jsonify({"logged_in": False, "reason": "Session expired"})


def run_unfollower_scan(task_id, username, ig_user=None, ig_pass=None, session_id=None):
    """Background worker: scrape followers, save snapshot, compare with previous."""
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass, session_id=session_id)

        tasks[task_id]["progress"] = "Loading profile..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            raise Exception("Profile is private and you don't follow them")

        # Get the profile follower count (always available publicly)
        with open(Path(OUTPUT_DIR) / username / "profile.json") as f:
            profile_data = json.load(f)
        profile_follower_count = profile_data.get("followers", 0)

        tasks[task_id]["progress"] = "Retrieving followers..."
        followers = scrape_followers(L, profile_obj, OUTPUT_DIR)

        if not followers:
            tasks[task_id]["progress"] = "No login — using profile count only..."

        tasks[task_id]["progress"] = "Saving snapshot..."
        save_follower_snapshot(followers, username, OUTPUT_DIR)

        tasks[task_id]["progress"] = "Comparing with previous snapshots..."
        snapshots = load_follower_snapshots(username, OUTPUT_DIR)

        report = {
            "username": username,
            "profile_follower_count": profile_follower_count,
            "snapshot_count": len(snapshots),
            "latest_snapshot": {
                "timestamp": snapshots[-1]["timestamp"] if snapshots else None,
                "count": snapshots[-1]["count"] if snapshots else 0,
            },
            "login_required": len(followers) == 0,
        }

        if len(snapshots) >= 2:
            comparison = compare_follower_snapshots(snapshots[-2], snapshots[-1])
            unfollower_analysis = analyze_unfollowers(comparison["unfollowers"])
            new_follower_analysis = analyze_unfollowers(comparison["new_followers"])

            report["comparison"] = comparison
            report["unfollower_analysis"] = unfollower_analysis
            report["new_follower_analysis"] = new_follower_analysis

            # Build history from all consecutive snapshot pairs
            history = []
            for i in range(1, len(snapshots)):
                comp = compare_follower_snapshots(snapshots[i - 1], snapshots[i])
                history.append({
                    "from": comp["old_timestamp"],
                    "to": comp["new_timestamp"],
                    "unfollower_count": comp["unfollower_count"],
                    "new_follower_count": comp["new_follower_count"],
                    "net_change": comp["net_change"],
                    "old_count": comp["old_count"],
                    "new_count": comp["new_count"],
                })
            report["history"] = history
        else:
            report["comparison"] = None
            report["message"] = "First snapshot saved. Run again later to detect unfollowers."

        # Save report
        report_path = Path(OUTPUT_DIR) / username / "unfollowers.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        # Persist to database (survives Render restarts)
        try:
            with app.app_context():
                db_save_report(username, 'unfollowers', report)
        except Exception:
            pass  # file save is the fallback

        tasks[task_id]["status"] = "done"
        tasks[task_id]["result"] = report

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)


@app.post("/api/unfollowers/scan")
@login_required
def api_unfollower_scan():
    data = request.json or {}
    username = data.get("username", "").strip().lstrip("@")
    if not username:
        return jsonify({"error": "Username required"}), 400

    ok, err = validate_scan_username(username)
    if not ok:
        return err

    # Free users: only one scan allowed
    if current_user.role != "admin" and not current_user.is_pro:
        if current_user.has_used_trial("unfollowers"):
            return jsonify({
                "error": "You've used your free unfollower scan. Upgrade to Pro ($6/mo) for unlimited scans.",
                "upgrade": True
            }), 403
        # Mark trial as used
        current_user.mark_trial_used("unfollowers")
        db.session.commit()

    task_id = str(uuid.uuid4())[:8]
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_unfollower_scan,
        args=(task_id, username, ig_user, ig_pass, get_ig_session_id()),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/unfollowers/<username>")
@api_can_view_account
def api_unfollowers(username):
    # Try database first (survives Render restarts)
    db_data = db_get_report(username, 'unfollowers')
    if db_data:
        return jsonify(db_data)
    # Fall back to local file
    report_path = Path(OUTPUT_DIR) / username / "unfollowers.json"
    if not report_path.exists():
        return jsonify({"error": "No unfollower report found. Run a scan first."}), 404
    with open(report_path) as f:
        return jsonify(json.load(f))


@app.get("/api/unfollowers/<username>/snapshots")
@api_can_view_account
def api_snapshots(username):
    snapshots = load_follower_snapshots(username, OUTPUT_DIR)
    # Return metadata only (not full follower lists)
    return jsonify([
        {"timestamp": s["timestamp"], "count": s["count"]}
        for s in snapshots
    ])


def run_lurker_scan(task_id, username, post_limit=20,
                    ig_user=None, ig_pass=None, session_id=None):
    """Background worker: scrape followers + engagement + stories, then analyze lurkers."""
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass, session_id=session_id)

        tasks[task_id]["progress"] = "Loading profile..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            raise Exception("Profile is private and you don't follow them")

        # Scrape followers
        tasks[task_id]["progress"] = "Retrieving followers..."
        followers = scrape_followers(L, profile_obj, OUTPUT_DIR)

        # Scrape post engagement (likers + commenters)
        tasks[task_id]["progress"] = f"Analyzing engagement on {post_limit} recent posts..."
        engagement_map = scrape_post_likers(L, profile_obj, OUTPUT_DIR, limit=post_limit)

        # Scrape story viewers
        tasks[task_id]["progress"] = "Checking story viewers..."
        scrape_story_viewers(L, profile_obj, OUTPUT_DIR)

        # Load story viewer history
        story_history = load_story_viewer_history(username, OUTPUT_DIR)

        # Run analysis
        tasks[task_id]["progress"] = "Analyzing lurkers and engagement patterns..."
        report = analyze_lurkers(followers, engagement_map, story_history)
        report["username"] = username
        report["analyzed_at"] = datetime.now().isoformat()

        # Save report
        report_path = Path(OUTPUT_DIR) / username / "lurkers.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        # Persist to database (survives Render restarts)
        try:
            with app.app_context():
                db_save_report(username, 'lurkers', report)
        except Exception:
            pass  # file save is the fallback

        tasks[task_id]["status"] = "done"
        tasks[task_id]["result"] = report

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)


@app.post("/api/lurkers/scan")
@pro_required("lurkers")
def api_lurker_scan():
    data = request.json or {}
    username = data.get("username", "").strip().lstrip("@")
    if not username:
        return jsonify({"error": "Username required"}), 400

    ok, err = validate_scan_username(username)
    if not ok:
        return err

    task_id = str(uuid.uuid4())[:8]
    post_limit = data.get("post_limit", 20)
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_lurker_scan,
        args=(task_id, username, post_limit, ig_user, ig_pass, get_ig_session_id()),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/lurkers/<username>")
@api_can_view_account
def api_lurkers(username):
    # Try database first (survives Render restarts)
    db_data = db_get_report(username, 'lurkers')
    if db_data:
        return jsonify(db_data)
    # Fall back to local file
    report_path = Path(OUTPUT_DIR) / username / "lurkers.json"
    if not report_path.exists():
        return jsonify({"error": "No lurker report found. Run a scan first."}), 404
    with open(report_path) as f:
        return jsonify(json.load(f))


def run_relationship_scan(task_id, username, ig_user=None, ig_pass=None, session_id=None):
    """Background worker: scrape followers + following, compare relationships."""
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass, session_id=session_id)

        tasks[task_id]["progress"] = "Loading profile..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            raise Exception("Profile is private and you don't follow them")

        tasks[task_id]["progress"] = "Retrieving followers..."
        followers = scrape_followers(L, profile_obj, OUTPUT_DIR)

        tasks[task_id]["progress"] = "Retrieving following..."
        following = scrape_following(L, profile_obj, OUTPUT_DIR)

        tasks[task_id]["progress"] = "Analyzing relationships..."
        report = analyze_follow_relationship(followers, following)
        report["username"] = username
        report["analyzed_at"] = datetime.now().isoformat()

        # Add demographics analysis
        tasks[task_id]["progress"] = "Analyzing demographics..."
        report["demographics"] = analyze_follower_demographics(followers)

        # Save report
        report_path = Path(OUTPUT_DIR) / username / "relationships.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        # Persist to database (survives Render restarts)
        try:
            with app.app_context():
                db_save_report(username, 'relationships', report)
        except Exception:
            pass  # file save is the fallback

        tasks[task_id]["status"] = "done"
        tasks[task_id]["result"] = report

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)


@app.post("/api/relationships/scan")
@login_required
def api_relationship_scan():
    data = request.json or {}
    username = data.get("username", "").strip().lstrip("@")
    if not username:
        return jsonify({"error": "Username required"}), 400

    ok, err = validate_scan_username(username)
    if not ok:
        return err

    # Free users: only one scan allowed
    if current_user.role != "admin" and not current_user.is_pro:
        if current_user.has_used_trial("relationships"):
            return jsonify({
                "error": "You've used your free relationships scan. Upgrade to Pro ($6/mo) for unlimited scans.",
                "upgrade": True
            }), 403
        current_user.mark_trial_used("relationships")
        db.session.commit()

    task_id = str(uuid.uuid4())[:8]
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_relationship_scan,
        args=(task_id, username, ig_user, ig_pass, get_ig_session_id()),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/relationships/<username>")
@api_can_view_account
def api_relationships(username):
    # Try database first (survives Render restarts)
    data = db_get_report(username, 'relationships')
    if not data:
        # Fall back to local file
        report_path = Path(OUTPUT_DIR) / username / "relationships.json"
        if not report_path.exists():
            return jsonify({"error": "No relationship report found. Run a scan first."}), 404
        with open(report_path) as f:
            data = json.load(f)

    # Free users: strip gender analysis data + limit lists to 20
    if current_user.role != "admin" and not current_user.is_pro:
        data.pop("fans_gender", None)
        data.pop("not_following_back_gender", None)
        data.pop("mutual_gender", None)
        # Strip gender from individual profiles and cap at 20
        FREE_LIST_LIMIT = 20
        for key in ["fans", "not_following_back", "mutual"]:
            for p in data.get(key, []):
                p.pop("gender", None)
            full_list = data.get(key, [])
            if len(full_list) > FREE_LIST_LIMIT:
                data[key] = full_list[:FREE_LIST_LIMIT]
                data[f"{key}_truncated"] = True
        data["is_free"] = True

    return jsonify(data)


def run_advisor_scan(task_id, username, post_limit=50, ig_user=None, ig_pass=None, session_id=None):
    """Background worker: scrape posts and analyze content performance."""
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass, session_id=session_id)

        tasks[task_id]["progress"] = "Loading profile..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        with open(Path(OUTPUT_DIR) / username / "profile.json") as f:
            profile_data = json.load(f)

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            raise Exception("Profile is private and you don't follow them")

        tasks[task_id]["progress"] = f"Fetching posts (up to {post_limit})..."
        posts_data = scrape_posts(
            L, profile_obj, OUTPUT_DIR,
            limit=post_limit, download_media=False
        )

        # Load follower snapshots if available
        snapshots = load_follower_snapshots(username, OUTPUT_DIR)
        snap_meta = [{"timestamp": s["timestamp"], "count": s["count"]} for s in snapshots]

        tasks[task_id]["progress"] = "Analyzing content performance..."
        report = analyze_content_performance(posts_data, profile_data, snap_meta if snap_meta else None)
        report["username"] = username
        report["analyzed_at"] = datetime.now().isoformat()
        report["posts_analyzed"] = len(posts_data)
        report["followers"] = profile_data.get("followers", 0)

        # Save
        report_path = Path(OUTPUT_DIR) / username / "advisor.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        # Persist to database (survives Render restarts)
        try:
            with app.app_context():
                db_save_report(username, 'advisor', report)
        except Exception:
            pass  # file save is the fallback

        tasks[task_id]["status"] = "done"
        tasks[task_id]["result"] = report

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)


@app.post("/api/advisor/scan")
@pro_required("advisor")
def api_advisor_scan():
    data = request.json or {}
    username = data.get("username", "").strip().lstrip("@")
    if not username:
        return jsonify({"error": "Username required"}), 400

    ok, err = validate_scan_username(username)
    if not ok:
        return err

    task_id = str(uuid.uuid4())[:8]
    post_limit = data.get("post_limit", 50)
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_advisor_scan,
        args=(task_id, username, post_limit, ig_user, ig_pass, get_ig_session_id()),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/advisor/<username>")
@api_can_view_account
def api_advisor(username):
    db_data = db_get_report(username, 'advisor')
    if db_data:
        return jsonify(db_data)
    report_path = Path(OUTPUT_DIR) / username / "advisor.json"
    if not report_path.exists():
        return jsonify({"error": "No advisor report found. Run a scan first."}), 404
    with open(report_path) as f:
        return jsonify(json.load(f))


def run_studio_scan(task_id, username, post_limit=50, ig_user=None, ig_pass=None, session_id=None):
    """Background worker: analyze content and generate studio recommendations."""
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass, session_id=session_id)

        tasks[task_id]["progress"] = "Loading profile..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        with open(Path(OUTPUT_DIR) / username / "profile.json") as f:
            profile_data = json.load(f)

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            raise Exception("Profile is private and you don't follow them")

        tasks[task_id]["progress"] = f"Fetching posts (up to {post_limit})..."
        posts_data = scrape_posts(L, profile_obj, OUTPUT_DIR, limit=post_limit, download_media=False)

        tasks[task_id]["progress"] = "Analyzing content categories..."
        report = analyze_content_studio(profile_data, posts_data)
        report["username"] = username
        report["analyzed_at"] = datetime.now().isoformat()
        report["posts_analyzed"] = len(posts_data)

        # Save
        report_path = Path(OUTPUT_DIR) / username / "studio.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        # Save to DB
        try:
            with app.app_context():
                db_save_report(username, 'studio', report)
        except Exception:
            pass

        tasks[task_id]["status"] = "done"
        tasks[task_id]["result"] = report

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)


@app.post("/api/studio/scan")
@pro_required("advisor")
def api_studio_scan():
    data = request.json or {}
    username = data.get("username", "").strip().lstrip("@")
    if not username:
        return jsonify({"error": "Username required"}), 400

    ok, err = validate_scan_username(username)
    if not ok:
        return err

    task_id = str(uuid.uuid4())[:8]
    post_limit = data.get("post_limit", 50)
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_studio_scan,
        args=(task_id, username, post_limit, ig_user, ig_pass, get_ig_session_id()),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/studio/<username>")
@api_can_view_account
def api_studio(username):
    db_data = db_get_report(username, 'studio')
    if db_data:
        return jsonify(db_data)
    report_path = Path(OUTPUT_DIR) / username / "studio.json"
    if not report_path.exists():
        return jsonify({"error": "No studio report found. Run a scan first."}), 404
    with open(report_path) as f:
        return jsonify(json.load(f))


# ── Billing / Subscription ───────────────────────────────────────────────────

LEMONSQUEEZY_CHECKOUT_URL = os.environ.get("LEMONSQUEEZY_CHECKOUT_URL", "")
LEMONSQUEEZY_CREATOR_CHECKOUT_URL = os.environ.get("LEMONSQUEEZY_CREATOR_CHECKOUT_URL", "")
LEMONSQUEEZY_WEBHOOK_SECRET = os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET", "")


@app.route("/pricing")
def pricing_page():
    return render_template("pricing.html")


@app.route("/billing")
@login_required
def billing_page():
    return render_template("billing.html")


@app.get("/api/billing/checkout")
@login_required
def api_billing_checkout():
    """Return the LemonSqueezy checkout URL with user email prefilled."""
    tier = request.args.get("tier", "pro")
    if tier == "creator":
        checkout = LEMONSQUEEZY_CREATOR_CHECKOUT_URL
    else:
        checkout = LEMONSQUEEZY_CHECKOUT_URL
    if not checkout:
        return jsonify({"error": "Billing not configured for this tier"}), 500
    sep = "&" if "?" in checkout else "?"
    checkout += f"{sep}checkout[email]={current_user.email}&checkout[custom][user_id]={current_user.id}"
    return jsonify({"url": checkout})


@app.get("/api/billing/status")
@login_required
def api_billing_status():
    """Return current user's subscription status."""
    return jsonify({
        "tier": current_user.subscription_tier,
        "status": current_user.subscription_status,
        "is_pro": current_user.is_pro,
        "trial_used": current_user.trial_used or {},
    })


@app.post("/api/billing/webhook")
def api_billing_webhook():
    """LemonSqueezy webhook handler for subscription events."""
    import hashlib, hmac

    # Verify webhook signature
    if LEMONSQUEEZY_WEBHOOK_SECRET:
        signature = request.headers.get("X-Signature", "")
        payload = request.get_data()
        expected = hmac.new(
            LEMONSQUEEZY_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return jsonify({"error": "Invalid signature"}), 403

    data = request.json or {}
    event_name = data.get("meta", {}).get("event_name", "")
    attrs = data.get("data", {}).get("attributes", {})

    # Get user ID from custom data
    custom = data.get("meta", {}).get("custom_data", {})
    user_id = custom.get("user_id")
    user_email = attrs.get("user_email", "")

    # Find user
    user = None
    if user_id:
        user = db.session.get(User, int(user_id))
    if not user and user_email:
        user = User.query.filter_by(email=user_email.lower()).first()

    if not user:
        return jsonify({"ok": True, "note": "User not found"})

    subscription_id = str(data.get("data", {}).get("id", ""))

    # Save customer portal URL if available
    urls = attrs.get("urls", {})
    portal_url = urls.get("customer_portal", "")
    if portal_url:
        user.customer_portal_url = portal_url

    if event_name == "subscription_created":
        # Detect tier from variant/product name or amount
        amount = attrs.get("first_subscription_item", {}).get("price", 0)
        if amount and amount >= 1200:  # $12 in cents
            user.subscription_tier = "creator"
        else:
            user.subscription_tier = "pro"
        user.subscription_status = "active"
        user.subscription_id = subscription_id
        db.session.commit()

    elif event_name == "subscription_updated":
        status = attrs.get("status", "")
        if status == "active":
            user.subscription_tier = "pro"
            user.subscription_status = "active"
        elif status in ("cancelled", "expired", "past_due"):
            user.subscription_status = status
        user.subscription_id = subscription_id
        db.session.commit()

    elif event_name in ("subscription_cancelled", "subscription_expired"):
        user.subscription_status = "cancelled"
        user.subscription_tier = "free"
        db.session.commit()

    elif event_name == "subscription_payment_success":
        user.subscription_status = "active"
        user.subscription_tier = "pro"
        db.session.commit()

    return jsonify({"ok": True})


# ── User subscription info endpoint ─────────────────────────────────────────

@app.get("/api/me")
@login_required
def api_me():
    """Return current user info including subscription."""
    return jsonify({
        "id": current_user.id,
        "email": current_user.email,
        "display_name": current_user.display_name,
        "role": current_user.role,
        "is_pro": current_user.is_pro,
        "subscription_tier": current_user.subscription_tier,
        "instagram_username": current_user.instagram_username,
        "trial_used": current_user.trial_used or {},
    })


# ── AI Insights ─────────────────────────────────────────────────────────────

@app.post("/api/insights/<username>")
@api_can_view_account
def api_generate_insights(username):
    """Generate AI-powered cross-referenced insights from all user data."""
    import anthropic

    # Check AI limit
    allowed, remaining = current_user.use_ai_generation()
    if not allowed:
        return jsonify({"error": "AI generation limit reached. Upgrade for more.", "upgrade": True}), 403
    db.session.commit()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "AI not configured"}), 500

    # Gather all available data
    data_summary = {}

    # Profile
    profile_path = Path(OUTPUT_DIR) / username / "profile.json"
    if profile_path.exists():
        with open(profile_path) as f:
            data_summary["profile"] = json.load(f)

    # Relationships
    rel_data = db_get_report(username, 'relationships')
    if rel_data:
        data_summary["relationships"] = {
            "followers_count": rel_data.get("followers_count"),
            "following_count": rel_data.get("following_count"),
            "mutual_count": rel_data.get("mutual_count"),
            "fans_count": rel_data.get("fans_count"),
            "not_following_back_count": rel_data.get("not_following_back_count"),
        }

    # Unfollowers
    unf_data = db_get_report(username, 'unfollowers')
    if unf_data and unf_data.get("comparison"):
        comp = unf_data["comparison"]
        data_summary["unfollowers"] = {
            "unfollower_count": comp.get("unfollower_count"),
            "new_follower_count": comp.get("new_follower_count"),
            "net_change": comp.get("net_change"),
        }
        if unf_data.get("unfollower_analysis"):
            ua = unf_data["unfollower_analysis"]
            data_summary["unfollower_analysis"] = {
                "total": ua.get("total"),
                "gender_breakdown": ua.get("gender_breakdown"),
                "private_percentage": ua.get("private_percentage"),
                "no_name_percentage": ua.get("no_name_percentage"),
            }

    # Advisor / content performance
    adv_data = db_get_report(username, 'advisor')
    if adv_data:
        data_summary["content_performance"] = {
            "posts_analyzed": adv_data.get("posts_analyzed"),
            "best_hours": adv_data.get("best_hours"),
            "best_day": adv_data.get("best_day"),
            "engagement_trend": adv_data.get("engagement_trend"),
            "content_type_performance": adv_data.get("content_type_performance"),
            "recommendations": adv_data.get("recommendations"),
        }

    # Studio / categories
    studio_data = db_get_report(username, 'studio')
    if studio_data:
        data_summary["categories"] = studio_data.get("categories", [])
        data_summary["performance_comparison"] = studio_data.get("performance_comparison")

    # Recent posts
    posts_path = Path(OUTPUT_DIR) / username / "posts.json"
    if posts_path.exists():
        with open(posts_path) as f:
            posts = json.load(f)
            # Summarize recent posts
            data_summary["recent_posts"] = [{
                "date": p.get("date", "")[:10],
                "type": p.get("typename"),
                "likes": p.get("likes"),
                "comments": p.get("comments_count"),
                "hashtags_count": len(p.get("hashtags", [])),
                "caption_length": len(p.get("caption") or ""),
            } for p in posts[:20]]

    if not data_summary:
        return jsonify({"error": "No data available. Run some scans first."}), 404

    prompt = f"""You are an expert Instagram growth strategist and data analyst. Analyze this Instagram account data and provide actionable, cross-referenced insights.

Account: @{username}
Data: {json.dumps(data_summary, indent=2, default=str)}

Generate 6-8 detailed insights in JSON format. Each insight should:
1. Cross-reference multiple data points (e.g., connect unfollower patterns with content type)
2. Be specific with numbers from the data
3. Include actionable advice
4. Be written in a friendly, professional tone

Categories of insights to cover:
- Follower health (growth, unfollowers, ghost followers)
- Content performance (what works, what doesn't)
- Audience insights (who follows, who unfollowed, gender patterns)
- Growth opportunities (what to do next)
- Warnings (declining metrics, concerning patterns)
- Quick wins (easy things to improve right now)

Return ONLY valid JSON, no markdown:
{{
    "insights": [
        {{
            "title": "Short title",
            "category": "growth|content|audience|opportunity|warning|quick_win",
            "icon": "emoji",
            "text": "Detailed insight text with specific numbers and advice",
            "priority": "high|medium|low"
        }}
    ],
    "health_score": 0-100,
    "health_label": "Excellent|Good|Needs Attention|Critical",
    "summary": "One sentence overall summary"
}}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        import re
        response_text = message.content[0].text.strip()
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            result = json.loads(json_match.group())
            result["ai_remaining"] = current_user.ai_remaining
            # Save to DB
            try:
                with app.app_context():
                    db_save_report(username, 'insights', result)
            except Exception:
                pass
            return jsonify(result)
        return jsonify({"error": "AI returned invalid format"}), 500

    except Exception as e:
        return jsonify({"error": f"AI failed: {str(e)}"}), 500


@app.get("/api/insights/<username>")
@api_can_view_account
def api_get_insights(username):
    """Get cached insights."""
    data = db_get_report(username, 'insights')
    if data:
        return jsonify(data)
    return jsonify({"error": "No insights yet. Click Generate to create them."}), 404


# ── Content Planner API ──────────────────────────────────────────────────────

@app.get("/api/planner/posts")
@login_required
def api_planner_list():
    """List all planned posts for current user."""
    posts = PlannedPost.query.filter_by(user_id=current_user.id).order_by(PlannedPost.scheduled_at.asc()).all()
    return jsonify([p.to_dict() for p in posts])


@app.post("/api/planner/posts")
@login_required
def api_planner_create():
    """Create a new planned post."""
    data = request.json or {}
    post = PlannedPost(
        user_id=current_user.id,
        title=data.get("title", ""),
        caption=data.get("caption", ""),
        hashtags=data.get("hashtags", ""),
        media_type=data.get("media_type", "image"),
        scheduled_at=datetime.fromisoformat(data["scheduled_at"]) if data.get("scheduled_at") else None,
        status=data.get("status", "draft"),
        notes=data.get("notes", ""),
        category=data.get("category", ""),
    )
    db.session.add(post)
    db.session.commit()
    return jsonify({"ok": True, "post": post.to_dict()})


@app.post("/api/planner/posts/<int:post_id>")
@login_required
def api_planner_update(post_id):
    """Update a planned post."""
    post = PlannedPost.query.filter_by(id=post_id, user_id=current_user.id).first()
    if not post:
        return jsonify({"error": "Post not found"}), 404
    data = request.json or {}
    if "title" in data: post.title = data["title"]
    if "caption" in data: post.caption = data["caption"]
    if "hashtags" in data: post.hashtags = data["hashtags"]
    if "media_type" in data: post.media_type = data["media_type"]
    if "scheduled_at" in data:
        post.scheduled_at = datetime.fromisoformat(data["scheduled_at"]) if data["scheduled_at"] else None
    if "status" in data: post.status = data["status"]
    if "notes" in data: post.notes = data["notes"]
    if "category" in data: post.category = data["category"]
    db.session.commit()
    return jsonify({"ok": True, "post": post.to_dict()})


@app.delete("/api/planner/posts/<int:post_id>")
@login_required
def api_planner_delete(post_id):
    """Delete a planned post."""
    post = PlannedPost.query.filter_by(id=post_id, user_id=current_user.id).first()
    if not post:
        return jsonify({"error": "Post not found"}), 404
    db.session.delete(post)
    db.session.commit()
    return jsonify({"ok": True})


@app.post("/api/planner/generate-all")
@login_required
def api_generate_all():
    """AI-generate caption, hashtags, best time using Claude API."""
    import anthropic
    from datetime import timedelta

    data = request.json or {}
    description = data.get("description", "my post")
    category = data.get("category", "lifestyle")
    media_type = data.get("media_type", "image")

    # Check AI generation limit
    allowed, remaining = current_user.use_ai_generation()
    if not allowed:
        tier = current_user.subscription_tier or "free"
        if tier == "free":
            msg = "You've used all 3 free AI generations. Upgrade to Pro ($6/mo) for 20/month or Creator ($12/mo) for 200/month."
        elif tier == "pro":
            msg = "You've used all 20 AI generations this month. Upgrade to Creator ($12/mo) for 200/month."
        else:
            msg = "You've reached your AI generation limit this month."
        return jsonify({"error": msg, "upgrade": True}), 403
    db.session.commit()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "AI not configured — missing API key"}), 500

    prompt = f"""You are an expert Instagram content strategist. Generate content for an Instagram post.

Topic/Idea: {description}
Content Category: {category}
Content Type: {media_type} (photo/carousel/reel/story/video)

Generate the following in JSON format ONLY (no markdown, no explanation, just valid JSON):
{{
    "caption": "A compelling Instagram caption (150-300 chars). Include relevant emojis. Include a call-to-action (ask a question, ask to save/share). Make it engaging and authentic, not generic. If it's a reel add 'Watch till the end!', carousel add 'Swipe for more!'",
    "hashtags": "20 relevant hashtags separated by spaces, each starting with #. Mix popular (1M+ posts) and niche (10K-100K posts) hashtags. Include hashtags specific to the topic.",
    "best_day": "Best day of week to post this type of {category} content",
    "best_time": "Best time to post (HH:MM format, 24h)",
    "notes": "One sentence tip about why this timing and format works for {category} content"
}}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text.strip()

        # Parse JSON from response
        import re
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            ai_data = json.loads(json_match.group())
        else:
            return jsonify({"error": "AI returned invalid format"}), 500

        # Calculate suggested date
        best_day = ai_data.get("best_day", "Wednesday")
        best_time = ai_data.get("best_time", "11:00")
        today = datetime.utcnow()
        days_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
        target_day = days_map.get(best_day.lower(), 2)
        days_ahead = (target_day - today.weekday() + 7) % 7
        if days_ahead == 0:
            days_ahead = 7
        suggested_date = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        return jsonify({
            "caption": ai_data.get("caption", ""),
            "hashtags": ai_data.get("hashtags", ""),
            "best_time": f"{best_day} at {best_time}",
            "suggested_date": suggested_date,
            "suggested_time": best_time,
            "notes": ai_data.get("notes", ""),
            "ai_remaining": current_user.ai_remaining,
            "ai_limit": current_user.ai_limit,
        })

    except Exception as e:
        return jsonify({"error": f"AI generation failed: {str(e)}"}), 500


@app.post("/api/planner/generate-caption")
@login_required
def api_generate_caption():
    """Generate caption suggestions based on category and description."""
    data = request.json or {}
    description = data.get("description", "")
    category = data.get("category", "lifestyle")
    media_type = data.get("media_type", "image")

    # Rule-based caption generation (no AI API needed)
    templates = {
        "beauty": [
            f"Glow up loading... ✨ {description}\n\nDrop a 💖 if you love this look!",
            f"New look, who dis? 💄 {description}\n\nSave this for your next inspo!",
            f"Beauty is about being comfortable in your own skin 🌸\n\n{description}",
        ],
        "fitness": [
            f"No excuses, just results 💪\n\n{description}\n\nTag your gym buddy!",
            f"The only bad workout is the one that didn't happen 🔥\n\n{description}",
            f"Progress, not perfection 📈\n\n{description}\n\nWhat's your goal?",
        ],
        "food": [
            f"Eat well, feel well 🍽️\n\n{description}\n\nWould you try this? 👇",
            f"Made with love (and a little extra garlic) 🧄❤️\n\n{description}",
            f"Food is my love language 😋\n\n{description}\n\nSave for later!",
        ],
        "travel": [
            f"Take me back ✈️\n\n{description}\n\nWhere's your dream destination?",
            f"Not all who wander are lost 🌍\n\n{description}",
            f"Collecting moments, not things 📸\n\n{description}\n\nSave this spot!",
        ],
        "fashion": [
            f"Outfit of the day ✨\n\n{description}\n\nYay or nay? 👗",
            f"Style is a way to say who you are without speaking 💫\n\n{description}",
            f"Dress like you're already famous 👑\n\n{description}\n\nWhat would you pair with this?",
        ],
        "lifestyle": [
            f"Living my best life ☀️\n\n{description}\n\nDouble tap if you agree!",
            f"It's the little things ✨\n\n{description}",
            f"Just another day in paradise 🌿\n\n{description}\n\nWhat does your ideal day look like?",
        ],
        "tech": [
            f"The future is now 🚀\n\n{description}\n\nThoughts? 👇",
            f"Tech that changes everything 💡\n\n{description}",
            f"Innovation at its finest 🔧\n\n{description}\n\nSave for reference!",
        ],
        "art": [
            f"Art speaks where words fail 🎨\n\n{description}\n\nWhat do you see?",
            f"Every canvas is a journey ✨\n\n{description}",
            f"Creating is my therapy 🖌️\n\n{description}\n\nWould you hang this on your wall?",
        ],
        "music": [
            f"Feel the rhythm 🎵\n\n{description}\n\nTag someone who needs to hear this!",
            f"Music is the soundtrack of life 🎤\n\n{description}",
            f"Lost in the melody 🎶\n\n{description}\n\nWhat's on your playlist?",
        ],
        "business": [
            f"Hustle in silence, let success make the noise 📊\n\n{description}",
            f"Building something great 🏗️\n\n{description}\n\nWhat's your next big move?",
            f"Success is a journey, not a destination 🎯\n\n{description}",
        ],
        "gaming": [
            f"Game on! 🎮\n\n{description}\n\nDrop your gamertag below!",
            f"One more game... said no gamer ever 😂\n\n{description}",
            f"Level up 🕹️\n\n{description}\n\nWhat are you playing right now?",
        ],
        "education": [
            f"Knowledge is power 📚\n\n{description}\n\nSave this for later!",
            f"Learn something new every day 💡\n\n{description}",
            f"Did you know? 🤔\n\n{description}\n\nShare with someone who needs this!",
        ],
    }

    captions = templates.get(category, templates["lifestyle"])

    # Add media-type specific hooks
    if media_type == "reel":
        captions = [c + "\n\n🎬 Watch till the end!" for c in captions]
    elif media_type == "story":
        captions = [c + "\n\n📲 Swipe up for more!" for c in captions]
    elif media_type == "carousel":
        captions = [c + "\n\n👉 Swipe for more!" for c in captions]

    return jsonify({"captions": captions})


if __name__ == "__main__":
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    print("\n  InstaScope running at http://localhost:8080\n")
    app.run(debug=True, port=8080, use_reloader=False)
