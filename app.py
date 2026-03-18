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
    PostData, Report, ScanLog, StoryViewer, User,
)

from analyzer import (
    analyze_authenticity,
    analyze_content_performance,
    analyze_follow_relationship,
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
            conn.commit()


# ── Auth decorators ─────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


def can_view_account(f):
    """Decorator: checks user can view the <username> in the URL."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
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
                 ig_user=None, ig_pass=None):
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass)

        tasks[task_id]["progress"] = "Scraping profile info..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        with open(Path(OUTPUT_DIR) / username / "profile.json") as f:
            profile_data = json.load(f)

        posts_data = []
        followers_sample = None

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            tasks[task_id]["progress"] = "Profile is private — limited analysis..."
        else:
            tasks[task_id]["progress"] = f"Scraping posts (up to {post_limit})..."
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
@login_required
def index():
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


# ── API ──────────────────────────────────────────────────────────────────────

@app.post("/api/analyze")
@login_required
def api_analyze():
    data = request.json or {}
    username = data.get("username", "").strip().lstrip("@")
    if not username:
        return jsonify({"error": "Username required"}), 400

    task_id = str(uuid.uuid4())[:8]
    post_limit = data.get("post_limit", 50)
    deep = data.get("deep", False)
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_analysis,
        args=(task_id, username, post_limit, deep, ig_user, ig_pass),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/status/<task_id>")
def api_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task)


@app.get("/api/report/<username>")
@api_can_view_account
def api_report(username):
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
    username = L.test_login()
    if not username:
        return jsonify({"error": "Invalid or expired sessionid"}), 401

    # Save to file (local dev)
    try:
        save_session_id(session_id)
    except Exception:
        pass

    # Save to DB (cloud)
    account = db_get_or_create_account(username)
    account.session_id = session_id
    db.session.commit()

    return jsonify({"ok": True, "username": username})


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


def run_unfollower_scan(task_id, username, ig_user=None, ig_pass=None):
    """Background worker: scrape followers, save snapshot, compare with previous."""
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass)

        tasks[task_id]["progress"] = "Loading profile..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            raise Exception("Profile is private and you don't follow them")

        # Get the profile follower count (always available publicly)
        with open(Path(OUTPUT_DIR) / username / "profile.json") as f:
            profile_data = json.load(f)
        profile_follower_count = profile_data.get("followers", 0)

        tasks[task_id]["progress"] = "Scraping followers (this may take a while)..."
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

    task_id = str(uuid.uuid4())[:8]
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_unfollower_scan,
        args=(task_id, username, ig_user, ig_pass),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/unfollowers/<username>")
@api_can_view_account
def api_unfollowers(username):
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
                    ig_user=None, ig_pass=None):
    """Background worker: scrape followers + engagement + stories, then analyze lurkers."""
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass)

        tasks[task_id]["progress"] = "Loading profile..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            raise Exception("Profile is private and you don't follow them")

        # Scrape followers
        tasks[task_id]["progress"] = "Scraping followers..."
        followers = scrape_followers(L, profile_obj, OUTPUT_DIR)

        # Scrape post engagement (likers + commenters)
        tasks[task_id]["progress"] = f"Scraping engagement on {post_limit} recent posts..."
        engagement_map = scrape_post_likers(L, profile_obj, OUTPUT_DIR, limit=post_limit)

        # Scrape story viewers
        tasks[task_id]["progress"] = "Scraping story viewers..."
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

    task_id = str(uuid.uuid4())[:8]
    post_limit = data.get("post_limit", 20)
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_lurker_scan,
        args=(task_id, username, post_limit, ig_user, ig_pass),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/lurkers/<username>")
@api_can_view_account
def api_lurkers(username):
    report_path = Path(OUTPUT_DIR) / username / "lurkers.json"
    if not report_path.exists():
        return jsonify({"error": "No lurker report found. Run a scan first."}), 404
    with open(report_path) as f:
        return jsonify(json.load(f))


def run_relationship_scan(task_id, username, ig_user=None, ig_pass=None):
    """Background worker: scrape followers + following, compare relationships."""
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass)

        tasks[task_id]["progress"] = "Loading profile..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            raise Exception("Profile is private and you don't follow them")

        tasks[task_id]["progress"] = "Scraping followers..."
        followers = scrape_followers(L, profile_obj, OUTPUT_DIR)

        tasks[task_id]["progress"] = "Scraping following..."
        following = scrape_following(L, profile_obj, OUTPUT_DIR)

        tasks[task_id]["progress"] = "Analyzing relationships..."
        report = analyze_follow_relationship(followers, following)
        report["username"] = username
        report["analyzed_at"] = datetime.now().isoformat()

        # Save report
        report_path = Path(OUTPUT_DIR) / username / "relationships.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

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

    task_id = str(uuid.uuid4())[:8]
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_relationship_scan,
        args=(task_id, username, ig_user, ig_pass),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/relationships/<username>")
@api_can_view_account
def api_relationships(username):
    report_path = Path(OUTPUT_DIR) / username / "relationships.json"
    if not report_path.exists():
        return jsonify({"error": "No relationship report found. Run a scan first."}), 404
    with open(report_path) as f:
        return jsonify(json.load(f))


def run_advisor_scan(task_id, username, post_limit=50, ig_user=None, ig_pass=None):
    """Background worker: scrape posts and analyze content performance."""
    tasks[task_id] = {"status": "running", "progress": "Initializing..."}
    try:
        tasks[task_id]["progress"] = "Connecting to Instagram..."
        L = get_loader(ig_user, ig_pass)

        tasks[task_id]["progress"] = "Loading profile..."
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)

        with open(Path(OUTPUT_DIR) / username / "profile.json") as f:
            profile_data = json.load(f)

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            raise Exception("Profile is private and you don't follow them")

        tasks[task_id]["progress"] = f"Scraping posts (up to {post_limit})..."
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

    task_id = str(uuid.uuid4())[:8]
    post_limit = data.get("post_limit", 50)
    ig_user = data.get("ig_username") or os.environ.get("IG_USERNAME")
    ig_pass = data.get("ig_password") or os.environ.get("IG_PASSWORD")

    thread = threading.Thread(
        target=run_advisor_scan,
        args=(task_id, username, post_limit, ig_user, ig_pass),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.get("/api/advisor/<username>")
@api_can_view_account
def api_advisor(username):
    report_path = Path(OUTPUT_DIR) / username / "advisor.json"
    if not report_path.exists():
        return jsonify({"error": "No advisor report found. Run a scan first."}), 404
    with open(report_path) as f:
        return jsonify(json.load(f))


# ── Billing / Subscription ───────────────────────────────────────────────────

LEMONSQUEEZY_CHECKOUT_URL = os.environ.get("LEMONSQUEEZY_CHECKOUT_URL", "")
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
    if not LEMONSQUEEZY_CHECKOUT_URL:
        return jsonify({"error": "Billing not configured"}), 500
    # Append user email and custom data to checkout URL
    checkout = LEMONSQUEEZY_CHECKOUT_URL
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


if __name__ == "__main__":
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    print("\n  InstaScope running at http://localhost:8080\n")
    app.run(debug=True, port=8080, use_reloader=False)
