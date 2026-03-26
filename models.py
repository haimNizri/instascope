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
    review_mode = db.Column(db.Boolean, default=False)  # Meta review account — only shows creator tools
    # Which Instagram accounts this user can view (comma-separated usernames, or '*' for all)
    allowed_accounts = db.Column(db.Text, default="")
    instagram_username = db.Column(db.String(64))  # their own IG username
    instagram_verified = db.Column(db.Boolean, default=False)  # confirmed via session cookie
    subscription_tier = db.Column(db.String(16), default="free")  # 'free', 'pro', 'creator'
    ai_generations_used = db.Column(db.Integer, default=0)  # monthly AI usage counter
    ai_reset_month = db.Column(db.String(7))  # 'YYYY-MM' — resets counter each month
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
        """Check if user has an active pro or creator subscription, or trial."""
        if self.role == "admin":
            return True
        if self.subscription_tier in ("pro", "creator") and self.subscription_status == "active":
            return True
        if self.trial_expires_at and self.trial_expires_at > datetime.utcnow():
            return True
        return False

    @property
    def is_creator(self):
        """Check if user has creator tier (highest)."""
        if self.role == "admin":
            return True
        if self.subscription_tier == "creator" and self.subscription_status == "active":
            return True
        return False

    @property
    def trial_days_left(self):
        """Days remaining on trial, or 0."""
        if not self.trial_expires_at:
            return 0
        delta = self.trial_expires_at - datetime.utcnow()
        return max(0, delta.days)

    @property
    def ai_limit(self):
        """Max AI generations per month based on tier."""
        if self.role == "admin":
            return 9999
        if self.subscription_tier == "creator" and self.subscription_status == "active":
            return 9999
        if self.subscription_tier == "pro" and self.subscription_status == "active":
            return 30
        if self.trial_expires_at and self.trial_expires_at > datetime.utcnow():
            return 30  # trial gets pro-level AI
        return 3  # free users get 3 total (taste)

    @property
    def ai_remaining(self):
        """AI generations remaining this month."""
        current_month = datetime.utcnow().strftime("%Y-%m")
        if self.ai_reset_month != current_month:
            return self.ai_limit
        return max(0, self.ai_limit - (self.ai_generations_used or 0))

    def use_ai_generation(self):
        """Consume one AI generation. Returns (allowed, remaining)."""
        current_month = datetime.utcnow().strftime("%Y-%m")
        # Reset counter on new month
        if self.ai_reset_month != current_month:
            self.ai_reset_month = current_month
            self.ai_generations_used = 0
        if self.ai_generations_used >= self.ai_limit:
            return False, 0
        self.ai_generations_used = (self.ai_generations_used or 0) + 1
        return True, self.ai_limit - self.ai_generations_used

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
            "photo_picker": False,
            "publishing": False,
            "media_upload": False,
            "ai_insights": False,
        }

        allowed = free_features.get(feature, False)
        if not allowed:
            if feature == "unfollowers_first" and self.has_used_trial("unfollowers"):
                return False, "You've used your free unfollower scan. Upgrade to Pro for unlimited scans."
            return False, "This feature requires a Pro subscription ($9/month) or Creator ($19/month)."
        return True, "free"

    def can_publish(self):
        """Check if user can publish directly to Instagram (Creator only)."""
        if self.role == "admin":
            return True
        return self.is_creator

    def can_use_photo_picker(self):
        """Check if user can use photo picker (Pro+)."""
        if self.role == "admin":
            return True
        return self.is_pro

    @property
    def monthly_upload_limit(self):
        """Max media uploads per month."""
        if self.role == "admin":
            return 9999
        if self.is_creator:
            return 9999
        if self.is_pro:
            return 50
        return 0

    @property
    def monthly_picker_limit(self):
        """Max photo picker batches per month."""
        if self.role == "admin":
            return 9999
        if self.is_creator:
            return 9999
        if self.is_pro:
            return 3
        return 0

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
            "is_creator": self.is_creator,
            "ai_remaining": self.ai_remaining,
            "ai_limit": self.ai_limit,
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
    media_urls = db.Column(db.JSON)  # list of URLs for carousel posts
    scheduled_at = db.Column(db.DateTime)
    status = db.Column(db.String(16), default="draft")  # draft, scheduled, published, skipped
    notes = db.Column(db.Text)
    category = db.Column(db.String(32))  # content category
    ig_container_id = db.Column(db.String(64))  # Graph API container ID during publish
    ig_media_id = db.Column(db.String(64))  # Graph API media ID after publish
    published_at = db.Column(db.DateTime)  # actual publish timestamp
    publish_error = db.Column(db.Text)  # error message if publish failed
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
            "media_urls": self.media_urls,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "status": self.status,
            "notes": self.notes,
            "category": self.category,
            "ig_media_id": self.ig_media_id,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "publish_error": self.publish_error,
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


class InstagramGraphAccount(db.Model):
    """Instagram Business/Creator account connected via Facebook Graph API for publishing."""
    __tablename__ = "instagram_graph_accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ig_user_id = db.Column(db.String(64), nullable=False)  # Instagram Business Account ID
    ig_username = db.Column(db.String(64))
    fb_page_id = db.Column(db.String(64))  # connected Facebook Page ID
    fb_page_name = db.Column(db.String(256))
    access_token = db.Column(db.Text, nullable=False)  # long-lived user access token
    token_expires_at = db.Column(db.DateTime)  # 60-day expiry
    token_refreshed_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("graph_accounts", lazy="dynamic"))


class MediaAsset(db.Model):
    """Uploaded media file stored in Cloudinary."""
    __tablename__ = "media_assets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    batch_id = db.Column(db.String(36), index=True)  # groups photos from a single dump session
    cloudinary_id = db.Column(db.String(256))  # Cloudinary public_id
    url = db.Column(db.Text, nullable=False)  # full Cloudinary URL
    thumbnail_url = db.Column(db.Text)  # auto-generated via Cloudinary transforms
    resource_type = db.Column(db.String(16), default="image")  # 'image' or 'video'
    format = db.Column(db.String(16))  # 'jpg', 'png', 'mp4', etc.
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    bytes = db.Column(db.Integer)
    ai_score = db.Column(db.Float)  # Smart Photo Picker score (1-10)
    ai_analysis = db.Column(db.JSON)  # detailed AI analysis breakdown
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("media_assets", lazy="dynamic"))
