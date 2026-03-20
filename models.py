"""
InstaScope Database Models — PostgreSQL via SQLAlchemy
"""

from datetime import datetime

import bcrypt
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Application user with role-based access."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(256), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(128))
    role = db.Column(db.String(16), nullable=False, default="user")  # 'admin' or 'user'
    is_active = db.Column(db.Boolean, default=False)  # admin must approve
    # Which Instagram accounts this user can view (comma-separated usernames, or '*' for all)
    allowed_accounts = db.Column(db.Text, default="")
    instagram_username = db.Column(db.String(64))  # their own IG username
    instagram_verified = db.Column(db.Boolean, default=False)  # confirmed via session cookie
    subscription_tier = db.Column(db.String(16), default="free")  # 'free' or 'pro'
    subscription_id = db.Column(db.String(128))  # LemonSqueezy subscription ID
    subscription_status = db.Column(db.String(32))  # 'active', 'cancelled', 'expired'
    customer_portal_url = db.Column(db.Text)  # LemonSqueezy customer portal for managing subscription
    trial_expires_at = db.Column(db.DateTime)  # admin-granted free trial expiry
    trial_used = db.Column(db.JSON, default=dict)  # tracks which free features were used {"relationships": true, "unfollowers": true}
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def check_password(self, password):
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())

    @property
    def is_pro(self):
        """Check if user has an active pro subscription or trial."""
        if self.role == "admin":
            return True
        if self.subscription_tier == "pro" and self.subscription_status == "active":
            return True
        # Check admin-granted trial
        if self.trial_expires_at and self.trial_expires_at > datetime.utcnow():
            return True
        return False

    @property
    def trial_days_left(self):
        """Days remaining on trial, or 0."""
        if not self.trial_expires_at:
            return 0
        delta = self.trial_expires_at - datetime.utcnow()
        return max(0, delta.days)

    def has_used_trial(self, feature):
        """Check if user already used their free trial for a feature."""
        used = self.trial_used or {}
        return used.get(feature, False)

    def mark_trial_used(self, feature):
        """Mark a free trial feature as used."""
        used = self.trial_used or {}
        used[feature] = True
        self.trial_used = used

    def can_use_feature(self, feature):
        """Check if user can use a feature. Returns (allowed, reason)."""
        if self.role == "admin":
            return True, "admin"
        if self.is_pro:
            return True, "pro"

        # Free tier limits
        free_features = {
            "relationships_basic": True,  # always allowed, view only
            "relationships_full": False,  # gender analysis etc — pro only
            "unfollowers_first": not self.has_used_trial("unfollowers"),  # one-time
            "unfollowers_scan": False,  # re-scan — pro only
            "lurkers": False,
            "advisor": False,
            "analysis_deep": False,
        }

        allowed = free_features.get(feature, False)
        if not allowed:
            if feature == "unfollowers_first" and self.has_used_trial("unfollowers"):
                return False, "You've used your free unfollower scan. Upgrade to Pro for unlimited scans."
            return False, "This feature requires a Pro subscription ($6/month)."
        return True, "free"

    def can_view(self, ig_username):
        """Check if this user can view a given Instagram account.
        Regular users can ONLY see their own verified account. Period."""
        if self.role == "admin":
            return True
        # Regular users: must be verified and can only see their own account
        if not self.instagram_verified:
            return False
        if not self.instagram_username:
            return False
        return ig_username.lower() == self.instagram_username.lower()

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "is_active": self.is_active,
            "allowed_accounts": self.allowed_accounts,
            "instagram_username": self.instagram_username,
            "subscription_tier": self.subscription_tier,
            "subscription_status": self.subscription_status,
            "is_pro": self.is_pro,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PlannedPost(db.Model):
    """Scheduled/planned Instagram post."""
    __tablename__ = "planned_posts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(256))
    caption = db.Column(db.Text)
    hashtags = db.Column(db.Text)  # space-separated hashtags
    media_type = db.Column(db.String(16), default="image")  # image, video, carousel, reel, story
    media_url = db.Column(db.Text)  # uploaded image URL or path
    scheduled_at = db.Column(db.DateTime)
    status = db.Column(db.String(16), default="draft")  # draft, scheduled, published, skipped
    notes = db.Column(db.Text)
    category = db.Column(db.String(32))  # content category
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("planned_posts", lazy="dynamic"))

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "caption": self.caption,
            "hashtags": self.hashtags,
            "media_type": self.media_type,
            "media_url": self.media_url,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "status": self.status,
            "notes": self.notes,
            "category": self.category,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Account(db.Model):
    """Instagram account being tracked."""
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(256))
    biography = db.Column(db.Text)
    external_url = db.Column(db.String(512))
    followers_count = db.Column(db.Integer, default=0)
    following_count = db.Column(db.Integer, default=0)
    posts_count = db.Column(db.Integer, default=0)
    is_private = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    profile_pic_url = db.Column(db.Text)
    business_category = db.Column(db.String(128))
    session_id = db.Column(db.Text)  # encrypted Instagram sessionid
    auto_scan = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    snapshots = db.relationship("FollowerSnapshot", backref="account", lazy="dynamic")
    scans = db.relationship("ScanLog", backref="account", lazy="dynamic")
    reports = db.relationship("Report", backref="account", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "full_name": self.full_name,
            "biography": self.biography,
            "followers_count": self.followers_count,
            "following_count": self.following_count,
            "posts_count": self.posts_count,
            "is_private": self.is_private,
            "is_verified": self.is_verified,
            "profile_pic_url": self.profile_pic_url,
            "auto_scan": self.auto_scan,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class FollowerSnapshot(db.Model):
    """Point-in-time snapshot of followers/following lists."""
    __tablename__ = "follower_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    snapshot_type = db.Column(db.String(16), nullable=False)  # 'followers' or 'following'
    count = db.Column(db.Integer, default=0)
    usernames = db.Column(db.JSON)  # {username: {full_name, is_private, is_verified}}
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FollowEvent(db.Model):
    """Individual follow/unfollow events detected between snapshots."""
    __tablename__ = "follow_events"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    event_type = db.Column(db.String(16), nullable=False)  # 'unfollowed', 'new_follower'
    target_username = db.Column(db.String(64), nullable=False, index=True)
    target_full_name = db.Column(db.String(256))
    target_is_private = db.Column(db.Boolean)
    target_is_verified = db.Column(db.Boolean)
    target_gender = db.Column(db.String(16))
    detected_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class PostData(db.Model):
    """Scraped Instagram post metadata."""
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    shortcode = db.Column(db.String(32), unique=True, nullable=False)
    typename = db.Column(db.String(32))  # GraphImage, GraphVideo, GraphSidecar
    caption = db.Column(db.Text)
    hashtags = db.Column(db.JSON)  # list of hashtags
    mentions = db.Column(db.JSON)  # list of mentions
    likes = db.Column(db.Integer, default=0)
    comments_count = db.Column(db.Integer, default=0)
    posted_at = db.Column(db.DateTime)
    is_video = db.Column(db.Boolean, default=False)
    video_view_count = db.Column(db.Integer)
    location = db.Column(db.String(256))
    scraped_at = db.Column(db.DateTime, default=datetime.utcnow)


class Report(db.Model):
    """Generated analysis reports (cached JSON)."""
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    report_type = db.Column(db.String(32), nullable=False, index=True)
    # types: 'unfollowers', 'relationships', 'advisor', 'lurkers', 'analysis'
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index("ix_reports_account_type", "account_id", "report_type"),
    )


class ScanLog(db.Model):
    """Log of automated and manual scans."""
    __tablename__ = "scan_logs"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    scan_type = db.Column(db.String(32), nullable=False)  # 'auto', 'manual'
    status = db.Column(db.String(16), nullable=False)  # 'running', 'done', 'error'
    details = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)


class StoryViewer(db.Model):
    """Story viewer records."""
    __tablename__ = "story_viewers"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    story_media_id = db.Column(db.String(64))
    viewer_username = db.Column(db.String(64), nullable=False)
    viewer_full_name = db.Column(db.String(256))
    viewer_is_follower = db.Column(db.Boolean)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)
