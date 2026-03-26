"""
InstaScope Configuration
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "instascope-dev-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///instascope.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }

    # Fix for Render/Neon: they provide postgres:// but SQLAlchemy needs postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)

    # LemonSqueezy
    LEMONSQUEEZY_CHECKOUT_URL = os.environ.get("LEMONSQUEEZY_CHECKOUT_URL", "")
    LEMONSQUEEZY_WEBHOOK_SECRET = os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET", "")

    # Facebook / Instagram Graph API
    FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID", "")
    FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "")
    FACEBOOK_REDIRECT_URI = os.environ.get("FACEBOOK_REDIRECT_URI", "")

    # Cloudinary (media uploads)
    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")
    CLOUDINARY_UPLOAD_PRESET = os.environ.get("CLOUDINARY_UPLOAD_PRESET", "")
