#!/usr/bin/env python3
"""
Instagram Scraper — scrape profiles, posts, reels, stories, comments,
followers, following, and hashtag feeds.

Usage:
    python scraper.py --help
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import instaloader


# ── helpers ──────────────────────────────────────────────────────────────────

SESSION_FILE = Path.home() / ".config" / "instascope" / "session.json"


def save_session_id(session_id):
    """Save Instagram sessionid for reuse."""
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SESSION_FILE, "w") as f:
        json.dump({"sessionid": session_id, "saved_at": datetime.now().isoformat()}, f)
    print(f"[+] Session saved to {SESSION_FILE}")


def load_saved_session_id():
    """Load previously saved sessionid from file or database."""
    # Try file first
    if SESSION_FILE.exists():
        with open(SESSION_FILE) as f:
            data = json.load(f)
            sid = data.get("sessionid")
            if sid:
                return sid

    # Try database
    try:
        from models import Account, db
        account = Account.query.filter(Account.session_id.isnot(None)).order_by(Account.updated_at.desc()).first()
        if account and account.session_id:
            return account.session_id
    except Exception:
        pass

    return None


def login_with_session_id(L, session_id):
    """Authenticate instaloader using a raw sessionid cookie."""
    L.context._session.cookies.set(
        "sessionid", session_id, domain=".instagram.com", path="/"
    )
    username = L.test_login()
    if username:
        # Set internal login state so get_followers() etc. work
        L.context.username = username
        csrftoken = L.context._session.cookies.get("csrftoken", domain=".instagram.com") or ""
        if csrftoken:
            L.context._session.headers["x-csrftoken"] = csrftoken
        print(f"[+] Logged in as {username} (via sessionid)")
        return True
    print("[!] sessionid is invalid or expired")
    return False


def get_loader(username=None, password=None, session_dir=None, session_id=None):
    """Create and optionally authenticate an Instaloader instance."""
    L = instaloader.Instaloader(
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,  # we handle comments separately
        save_metadata=True,
        compress_json=False,
        post_metadata_txt_pattern="",
        max_connection_attempts=3,
    )
    if session_dir:
        L.dirname_pattern = session_dir

    # 1. Explicit session_id (from UI paste)
    if session_id:
        if login_with_session_id(L, session_id):
            save_session_id(session_id)
            return L

    # 2. Username + password
    if username and password:
        try:
            L.login(username, password)
            print(f"[+] Logged in as {username}")
            return L
        except instaloader.exceptions.BadCredentialsException:
            print("[!] Bad credentials — continuing without login")
        except instaloader.exceptions.TwoFactorAuthRequiredException:
            code = input("[?] Enter 2FA code: ")
            L.two_factor_login(code)
            print(f"[+] Logged in as {username} (2FA)")
            return L

    # 3. Saved instaloader session file
    if username:
        try:
            L.load_session_from_file(username)
            print(f"[+] Loaded saved session for {username}")
            return L
        except FileNotFoundError:
            pass

    # 4. Previously saved sessionid from our app
    saved_sid = load_saved_session_id()
    if saved_sid:
        print("[*] Trying saved sessionid...")
        if login_with_session_id(L, saved_sid):
            return L
        print("[!] Saved sessionid expired")

    # 5. Environment variable
    env_sid = os.environ.get("IG_SESSION_ID")
    if env_sid:
        if login_with_session_id(L, env_sid):
            save_session_id(env_sid)
            return L

    print("[!] No login available — some features will be limited")
    return L


def save_json(data, filepath):
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"[+] Saved {filepath}")


# ── scrape functions ─────────────────────────────────────────────────────────

def _get_ig_session(session_id):
    """Create a requests session with Instagram auth and optional proxy."""
    import requests as _req

    session = _req.Session()
    session.cookies.set("sessionid", session_id, domain=".instagram.com")
    session.headers.update({
        "x-ig-app-id": "936619743392459",
        "User-Agent": "Instagram 317.0.0.0.62 Android (26/8.0.0; 480dpi; 1080x1920; samsung; SM-G950F; dreamlte; samsungexynos8895; en_US; 556062177)",
    })

    # Optional proxy support
    proxy = os.environ.get("PROXY_URL")
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    return session


def scrape_profile_fast(session_id, target, output_dir):
    """Fast profile scrape using Instagram private API."""
    session = _get_ig_session(session_id)

    # Try mobile API first (less blocked)
    try:
        resp = session.get(
            f"https://i.instagram.com/api/v1/users/web_profile_info/",
            params={"username": target},
            timeout=10,
        )
        if resp.status_code == 200:
            user = resp.json().get("data", {}).get("user", {})
            if user:
                info = _parse_web_profile(user, target)
                save_json(info, f"{output_dir}/{target}/profile.json")
                print(f"[+] Fast profile scraped: {target} ({info['followers']} followers)")
                return info
    except Exception as e:
        print(f"[!] Web profile API failed: {e}")

    # Fallback: search API
    try:
        resp = session.get(
            "https://i.instagram.com/api/v1/users/search/",
            params={"q": target, "count": 1},
            timeout=10,
        )
        if resp.status_code == 200:
            users = resp.json().get("users", [])
            if users and users[0].get("username", "").lower() == target.lower():
                u = users[0]
                user_id = u["pk"]
                # Get full profile
                resp2 = session.get(
                    f"https://i.instagram.com/api/v1/users/{user_id}/info/",
                    timeout=10,
                )
                if resp2.status_code == 200:
                    u2 = resp2.json().get("user", {})
                    info = {
                        "username": u2.get("username", target),
                        "full_name": u2.get("full_name", ""),
                        "biography": u2.get("biography", ""),
                        "external_url": u2.get("external_url", ""),
                        "followers": u2.get("follower_count", 0),
                        "following": u2.get("following_count", 0),
                        "posts_count": u2.get("media_count", 0),
                        "is_private": u2.get("is_private", False),
                        "is_verified": u2.get("is_verified", False),
                        "profile_pic_url": u2.get("hd_profile_pic_url_info", {}).get("url", u2.get("profile_pic_url", "")),
                        "business_category": u2.get("category", ""),
                        "user_id": str(user_id),
                        "scraped_at": datetime.now().isoformat(),
                    }
                    save_json(info, f"{output_dir}/{target}/profile.json")
                    print(f"[+] Fast profile scraped (v2): {target} ({info['followers']} followers)")
                    return info
    except Exception as e:
        print(f"[!] Search/info API failed: {e}")

    raise Exception(f"Could not fetch profile for {target} — Instagram may be blocking this server's IP")


def _parse_web_profile(user, target):
    """Parse web_profile_info response into our profile dict."""
    return {
        "username": user.get("username", target),
        "full_name": user.get("full_name", ""),
        "biography": user.get("biography", ""),
        "external_url": user.get("external_url", ""),
        "followers": user.get("edge_followed_by", {}).get("count", 0),
        "following": user.get("edge_follow", {}).get("count", 0),
        "posts_count": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
        "is_private": user.get("is_private", False),
        "is_verified": user.get("is_verified", False),
        "profile_pic_url": user.get("profile_pic_url_hd", user.get("profile_pic_url", "")),
        "business_category": user.get("category_name", ""),
        "user_id": user.get("id", ""),
        "scraped_at": datetime.now().isoformat(),
    }

    info = {
        "username": user.get("username", target),
        "full_name": user.get("full_name", ""),
        "biography": user.get("biography", ""),
        "external_url": user.get("external_url", ""),
        "followers": user.get("edge_followed_by", {}).get("count", 0),
        "following": user.get("edge_follow", {}).get("count", 0),
        "posts_count": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
        "is_private": user.get("is_private", False),
        "is_verified": user.get("is_verified", False),
        "profile_pic_url": user.get("profile_pic_url_hd", user.get("profile_pic_url", "")),
        "business_category": user.get("category_name", ""),
        "user_id": user.get("id", ""),
        "scraped_at": datetime.now().isoformat(),
    }
    save_json(info, f"{output_dir}/{target}/profile.json")
    print(f"[+] Fast profile scraped: {target} ({info['followers']} followers)")
    return info


def scrape_profile(L, target, output_dir):
    """Scrape basic profile information. Uses fast API first, falls back to instaloader."""
    session_id = load_saved_session_id()
    if session_id:
        try:
            info = scrape_profile_fast(session_id, target, output_dir)
            # Return a minimal object with needed attributes for compatibility
            class ProfileProxy:
                def __init__(self, data):
                    self.username = data["username"]
                    self.full_name = data["full_name"]
                    self.followers = data["followers"]
                    self.followees = data["following"]
                    self.mediacount = data["posts_count"]
                    self.is_private = data["is_private"]
                    self.is_verified = data["is_verified"]
                    self.userid = data.get("user_id", "")
                    self.followed_by_viewer = True  # assume accessible if we got data
                    self.profile_pic_url = data["profile_pic_url"]
            return ProfileProxy(info)
        except Exception as e:
            print(f"[!] Fast profile API failed ({e}), falling back to instaloader...")

    profile = instaloader.Profile.from_username(L.context, target)
    info = {
        "username": profile.username,
        "full_name": profile.full_name,
        "biography": profile.biography,
        "external_url": profile.external_url,
        "followers": profile.followers,
        "following": profile.followees,
        "posts_count": profile.mediacount,
        "is_private": profile.is_private,
        "is_verified": profile.is_verified,
        "profile_pic_url": str(profile.profile_pic_url),
        "business_category": profile.business_category_name,
        "scraped_at": datetime.now().isoformat(),
    }
    save_json(info, f"{output_dir}/{target}/profile.json")
    # download profile pic
    L.download_profilepic(profile)
    return profile


def scrape_posts(L, profile, output_dir, limit=None, download_media=True):
    """Scrape posts (images/videos/carousels) with metadata."""
    posts_data = []
    for i, post in enumerate(profile.get_posts()):
        if limit and i >= limit:
            break
        post_info = {
            "shortcode": post.shortcode,
            "url": f"https://www.instagram.com/p/{post.shortcode}/",
            "typename": post.typename,
            "caption": post.caption,
            "hashtags": list(post.caption_hashtags),
            "mentions": list(post.caption_mentions),
            "likes": post.likes,
            "comments_count": post.comments,
            "date": post.date_utc.isoformat(),
            "is_video": post.is_video,
            "video_view_count": post.video_view_count if post.is_video else None,
            "location": str(post.location) if post.location else None,
        }
        posts_data.append(post_info)
        if download_media:
            L.download_post(post, target=Path(output_dir) / profile.username)
        print(f"  [{i+1}] {post.shortcode} — {post.date_utc.date()}")
    save_json(posts_data, f"{output_dir}/{profile.username}/posts.json")
    return posts_data


def scrape_reels(L, profile, output_dir, limit=None):
    """Scrape reels (IGTV + Reels)."""
    reels_data = []
    try:
        for i, post in enumerate(profile.get_posts()):
            if limit and i >= limit:
                break
            if post.typename == "GraphVideo" and post.is_video:
                reel_info = {
                    "shortcode": post.shortcode,
                    "url": f"https://www.instagram.com/reel/{post.shortcode}/",
                    "caption": post.caption,
                    "likes": post.likes,
                    "comments_count": post.comments,
                    "date": post.date_utc.isoformat(),
                    "video_view_count": post.video_view_count,
                }
                reels_data.append(reel_info)
                L.download_post(post, target=Path(output_dir) / profile.username / "reels")
                print(f"  [reel {len(reels_data)}] {post.shortcode}")
    except Exception as e:
        print(f"[!] Error scraping reels: {e}")
    save_json(reels_data, f"{output_dir}/{profile.username}/reels.json")
    return reels_data


def scrape_stories(L, profile, output_dir):
    """Scrape current stories (requires login)."""
    stories_data = []
    try:
        for story in L.get_stories(userids=[profile.userid]):
            for item in story.get_items():
                story_info = {
                    "mediaid": item.mediaid,
                    "date": item.date_utc.isoformat(),
                    "is_video": item.is_video,
                    "url": str(item.url),
                }
                stories_data.append(story_info)
                L.download_storyitem(item, target=Path(output_dir) / profile.username / "stories")
                print(f"  [story] {item.mediaid}")
    except instaloader.exceptions.LoginRequiredException:
        print("[!] Login required to scrape stories")
    except Exception as e:
        print(f"[!] Error scraping stories: {e}")
    save_json(stories_data, f"{output_dir}/{profile.username}/stories.json")
    return stories_data


def scrape_comments(L, profile, output_dir, limit=None):
    """Scrape comments on posts."""
    all_comments = {}
    for i, post in enumerate(profile.get_posts()):
        if limit and i >= limit:
            break
        comments = []
        try:
            for comment in post.get_comments():
                comments.append({
                    "id": comment.id,
                    "owner": comment.owner.username,
                    "text": comment.text,
                    "created_at": comment.created_at_utc.isoformat(),
                    "likes": comment.likes_count,
                })
        except Exception as e:
            print(f"  [!] Could not get comments for {post.shortcode}: {e}")
        all_comments[post.shortcode] = comments
        print(f"  [{i+1}] {post.shortcode}: {len(comments)} comments")
    save_json(all_comments, f"{output_dir}/{profile.username}/comments.json")
    return all_comments


def scrape_followers_fast(session_id, user_id, output_dir, username):
    """Fast follower fetch using Instagram's private API (up to 200 per request)."""
    session = _get_ig_session(session_id)

    followers = []
    max_id = None
    page = 0

    while True:
        page += 1
        url = f"https://i.instagram.com/api/v1/friendships/{user_id}/followers/"
        params = {"count": 200}
        if max_id:
            params["max_id"] = max_id

        resp = session.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"[!] API returned {resp.status_code} on page {page}")
            break

        data = resp.json()
        users = data.get("users", [])
        for u in users:
            followers.append({
                "username": u.get("username", ""),
                "full_name": u.get("full_name", ""),
                "is_private": u.get("is_private", False),
                "is_verified": u.get("is_verified", False),
            })

        print(f"  [page {page}] fetched {len(users)} followers (total: {len(followers)})")

        if not data.get("next_max_id"):
            break
        max_id = data["next_max_id"]
        time.sleep(0.5)  # brief pause between pages

    save_json(followers, f"{output_dir}/{username}/followers.json")
    print(f"[+] Total followers collected: {len(followers)}")
    return followers


def scrape_followers(L, profile, output_dir):
    """Scrape followers list. Uses fast API if sessionid available, falls back to instaloader."""
    # Try fast API first
    session_id = load_saved_session_id()
    if session_id:
        try:
            return scrape_followers_fast(session_id, profile.userid, output_dir, profile.username)
        except Exception as e:
            print(f"[!] Fast API failed ({e}), falling back to instaloader...")

    # Fallback: slow instaloader method
    followers = []
    try:
        for follower in profile.get_followers():
            followers.append({
                "username": follower.username,
                "full_name": follower.full_name,
                "is_private": follower.is_private,
                "is_verified": follower.is_verified,
            })
            if len(followers) % 100 == 0:
                print(f"  ... {len(followers)} followers collected")
    except instaloader.exceptions.LoginRequiredException:
        print("[!] Login required to scrape followers")
    except Exception as e:
        print(f"[!] Stopped at {len(followers)} followers: {e}")
    save_json(followers, f"{output_dir}/{profile.username}/followers.json")
    print(f"[+] Total followers collected: {len(followers)}")
    return followers


def save_follower_snapshot(followers, username, output_dir):
    """Save a timestamped snapshot of the followers list for unfollower tracking."""
    snapshot_dir = Path(output_dir) / username / "follower_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "count": len(followers),
        "followers": {f["username"]: f for f in followers},
    }
    filepath = snapshot_dir / f"{timestamp}.json"
    save_json(snapshot, filepath)
    return filepath


def load_follower_snapshots(username, output_dir):
    """Load all follower snapshots sorted by time (oldest first)."""
    snapshot_dir = Path(output_dir) / username / "follower_snapshots"
    if not snapshot_dir.exists():
        return []
    snapshots = []
    for f in sorted(snapshot_dir.glob("*.json")):
        with open(f) as fh:
            data = json.load(fh)
            data["_file"] = str(f)
            snapshots.append(data)
    return snapshots


def compare_follower_snapshots(old_snapshot, new_snapshot):
    """Compare two snapshots and return unfollowers and new followers."""
    old_users = set(old_snapshot.get("followers", {}).keys())
    new_users = set(new_snapshot.get("followers", {}).keys())

    unfollowed_usernames = old_users - new_users
    new_follower_usernames = new_users - old_users

    unfollowers = []
    for u in unfollowed_usernames:
        info = old_snapshot["followers"].get(u, {})
        info["username"] = u
        unfollowers.append(info)

    new_followers = []
    for u in new_follower_usernames:
        info = new_snapshot["followers"].get(u, {})
        info["username"] = u
        new_followers.append(info)

    return {
        "old_timestamp": old_snapshot.get("timestamp"),
        "new_timestamp": new_snapshot.get("timestamp"),
        "old_count": old_snapshot.get("count", 0),
        "new_count": new_snapshot.get("count", 0),
        "unfollowers": sorted(unfollowers, key=lambda x: x.get("username", "")),
        "new_followers": sorted(new_followers, key=lambda x: x.get("username", "")),
        "unfollower_count": len(unfollowers),
        "new_follower_count": len(new_followers),
        "net_change": len(new_followers) - len(unfollowers),
    }


def scrape_following_fast(session_id, user_id, output_dir, username):
    """Fast following fetch using Instagram's private API."""
    session = _get_ig_session(session_id)

    following = []
    max_id = None
    page = 0

    while True:
        page += 1
        url = f"https://i.instagram.com/api/v1/friendships/{user_id}/following/"
        params = {"count": 200}
        if max_id:
            params["max_id"] = max_id

        resp = session.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"[!] API returned {resp.status_code} on page {page}")
            break

        data = resp.json()
        users = data.get("users", [])
        for u in users:
            following.append({
                "username": u.get("username", ""),
                "full_name": u.get("full_name", ""),
                "is_private": u.get("is_private", False),
                "is_verified": u.get("is_verified", False),
            })

        print(f"  [page {page}] fetched {len(users)} following (total: {len(following)})")

        if not data.get("next_max_id"):
            break
        max_id = data["next_max_id"]
        time.sleep(0.5)

    save_json(following, f"{output_dir}/{username}/following.json")
    print(f"[+] Total following collected: {len(following)}")
    return following


def scrape_following(L, profile, output_dir):
    """Scrape following list. Uses fast API if sessionid available."""
    session_id = load_saved_session_id()
    if session_id:
        try:
            return scrape_following_fast(session_id, profile.userid, output_dir, profile.username)
        except Exception as e:
            print(f"[!] Fast API failed ({e}), falling back to instaloader...")

    following = []
    try:
        for followee in profile.get_followees():
            following.append({
                "username": followee.username,
                "full_name": followee.full_name,
                "is_private": followee.is_private,
                "is_verified": followee.is_verified,
            })
            if len(following) % 100 == 0:
                print(f"  ... {len(following)} following collected")
    except instaloader.exceptions.LoginRequiredException:
        print("[!] Login required to scrape following")
    except Exception as e:
        print(f"[!] Stopped at {len(following)} following: {e}")
    save_json(following, f"{output_dir}/{profile.username}/following.json")
    print(f"[+] Total following collected: {len(following)}")
    return following


def scrape_hashtag(L, hashtag, output_dir, limit=50):
    """Scrape recent posts from a hashtag."""
    posts_data = []
    try:
        for i, post in enumerate(instaloader.Hashtag.from_name(L.context, hashtag).get_posts()):
            if i >= limit:
                break
            posts_data.append({
                "shortcode": post.shortcode,
                "owner": post.owner_username,
                "caption": post.caption,
                "likes": post.likes,
                "date": post.date_utc.isoformat(),
                "is_video": post.is_video,
            })
            print(f"  [{i+1}] #{hashtag} — {post.shortcode}")
    except Exception as e:
        print(f"[!] Error scraping hashtag: {e}")
    save_json(posts_data, f"{output_dir}/hashtags/{hashtag}.json")
    return posts_data


# ── Story viewer & engagement scraping ────────────────────────────────────────

def scrape_story_viewers(L, profile, output_dir):
    """Scrape current stories WITH viewer lists (requires login, must be your own profile)."""
    stories_with_viewers = []
    try:
        for story in L.get_stories(userids=[profile.userid]):
            for item in story.get_items():
                story_info = {
                    "mediaid": item.mediaid,
                    "date": item.date_utc.isoformat(),
                    "is_video": item.is_video,
                    "url": str(item.url),
                    "viewers": [],
                }
                # Viewer list is only available for your own stories
                try:
                    for viewer in item.get_viewers():
                        story_info["viewers"].append({
                            "username": viewer.username,
                            "full_name": viewer.full_name,
                            "is_private": viewer.is_private,
                            "is_verified": viewer.is_verified,
                        })
                except Exception:
                    pass  # Viewers not available (not own story or expired)

                stories_with_viewers.append(story_info)
                print(f"  [story] {item.mediaid} — {len(story_info['viewers'])} viewers")
    except instaloader.exceptions.LoginRequiredException:
        print("[!] Login required to scrape story viewers")
    except Exception as e:
        print(f"[!] Error scraping story viewers: {e}")

    # Save with timestamp for historical tracking
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    viewer_dir = Path(output_dir) / profile.username / "story_viewers"
    viewer_dir.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "stories": stories_with_viewers,
    }
    save_json(snapshot, viewer_dir / f"{timestamp}.json")

    # Also save latest
    save_json(snapshot, f"{output_dir}/{profile.username}/story_viewers_latest.json")
    print(f"[+] Story viewers collected for {len(stories_with_viewers)} stories")
    return stories_with_viewers


def load_story_viewer_history(username, output_dir):
    """Load all story viewer snapshots."""
    viewer_dir = Path(output_dir) / username / "story_viewers"
    if not viewer_dir.exists():
        return []
    history = []
    for f in sorted(viewer_dir.glob("*.json")):
        with open(f) as fh:
            history.append(json.load(fh))
    return history


def scrape_post_likers(L, profile, output_dir, limit=20):
    """Scrape likers for recent posts to build engagement map."""
    engagement_map = {}
    try:
        for i, post in enumerate(profile.get_posts()):
            if i >= limit:
                break
            likers = []
            try:
                for liker in post.get_likes():
                    likers.append({
                        "username": liker.username,
                        "full_name": liker.full_name,
                        "is_private": liker.is_private,
                        "is_verified": liker.is_verified,
                    })
            except Exception as e:
                print(f"  [!] Could not get likers for {post.shortcode}: {e}")

            commenters = []
            try:
                for comment in post.get_comments():
                    commenters.append({
                        "username": comment.owner.username,
                        "text": comment.text[:100],
                    })
            except Exception:
                pass

            engagement_map[post.shortcode] = {
                "shortcode": post.shortcode,
                "date": post.date_utc.isoformat(),
                "likes_count": post.likes,
                "comments_count": post.comments,
                "likers": likers,
                "commenters": commenters,
                "is_video": post.is_video,
                "caption_preview": (post.caption or "")[:80],
            }
            print(f"  [{i+1}] {post.shortcode} — {len(likers)} likers, {len(commenters)} commenters")
    except Exception as e:
        print(f"[!] Error scraping engagement: {e}")

    save_json(engagement_map, f"{output_dir}/{profile.username}/engagement_map.json")
    print(f"[+] Engagement data collected for {len(engagement_map)} posts")
    return engagement_map


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Instagram Scraper — profiles, posts, reels, stories, comments, followers, hashtags"
    )
    parser.add_argument("targets", nargs="+", help="Usernames or #hashtags to scrape")
    parser.add_argument("-u", "--username", help="Your Instagram username (for login)")
    parser.add_argument("-p", "--password", help="Your Instagram password")
    parser.add_argument("-o", "--output", default="output", help="Output directory (default: output)")
    parser.add_argument("--limit", type=int, default=None, help="Max posts to scrape per target")

    # what to scrape
    parser.add_argument("--all", action="store_true", help="Scrape everything")
    parser.add_argument("--profile", action="store_true", help="Scrape profile info")
    parser.add_argument("--posts", action="store_true", help="Scrape posts")
    parser.add_argument("--reels", action="store_true", help="Scrape reels")
    parser.add_argument("--stories", action="store_true", help="Scrape stories (requires login)")
    parser.add_argument("--comments", action="store_true", help="Scrape comments")
    parser.add_argument("--followers", action="store_true", help="Scrape followers (requires login)")
    parser.add_argument("--following", action="store_true", help="Scrape following (requires login)")
    parser.add_argument("--no-media", action="store_true", help="Skip downloading images/videos")

    args = parser.parse_args()

    # default to profile + posts if nothing specified
    if not any([args.all, args.profile, args.posts, args.reels,
                args.stories, args.comments, args.followers, args.following]):
        args.profile = True
        args.posts = True

    L = get_loader(args.username, args.password)
    output_dir = args.output

    for target in args.targets:
        print(f"\n{'='*50}")

        # hashtag
        if target.startswith("#"):
            tag = target.lstrip("#")
            print(f"[*] Scraping hashtag: #{tag}")
            scrape_hashtag(L, tag, output_dir, limit=args.limit or 50)
            continue

        # user profile
        print(f"[*] Scraping user: {target}")
        try:
            profile = scrape_profile(L, target, output_dir)
        except instaloader.exceptions.ProfileNotExistsException:
            print(f"[!] Profile '{target}' not found — skipping")
            continue

        if profile.is_private and not profile.followed_by_viewer:
            print(f"[!] Profile '{target}' is private and you don't follow them")
            print("    Only profile info was saved. Skipping posts/stories/etc.")
            continue

        if args.all or args.posts:
            print(f"\n[*] Scraping posts...")
            scrape_posts(L, profile, output_dir, limit=args.limit, download_media=not args.no_media)

        if args.all or args.reels:
            print(f"\n[*] Scraping reels...")
            scrape_reels(L, profile, output_dir, limit=args.limit)

        if args.all or args.stories:
            print(f"\n[*] Scraping stories...")
            scrape_stories(L, profile, output_dir)

        if args.all or args.comments:
            print(f"\n[*] Scraping comments...")
            scrape_comments(L, profile, output_dir, limit=args.limit)

        if args.all or args.followers:
            print(f"\n[*] Scraping followers...")
            scrape_followers(L, profile, output_dir)

        if args.all or args.following:
            print(f"\n[*] Scraping following...")
            scrape_following(L, profile, output_dir)

    print(f"\n{'='*50}")
    print(f"[+] Done! Output saved to: {output_dir}/")


if __name__ == "__main__":
    main()
