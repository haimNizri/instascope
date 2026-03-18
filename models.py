"""
InstaScope Database Models — PostgreSQL via SQLAlchemy
"""

from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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
