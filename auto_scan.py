#!/usr/bin/env python3
"""
Auto-scan script — runs all InstaScope scans for configured users.
Designed to be called by cron twice daily.
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Add project dir to path
sys.path.insert(0, str(Path(__file__).parent))

from scraper import (
    get_loader, scrape_profile, scrape_followers, scrape_following,
    scrape_posts, save_follower_snapshot, load_follower_snapshots,
    compare_follower_snapshots, scrape_story_viewers, scrape_post_likers,
    load_story_viewer_history,
)
from analyzer import (
    analyze_unfollowers, analyze_follow_relationship,
    analyze_content_performance, analyze_lurkers,
)

OUTPUT_DIR = str(Path(__file__).parent / "output")
LOG_FILE = str(Path(__file__).parent / "output" / "auto_scan.log")

# Configure which users to auto-scan
USERS = ["haimnizri"]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run_scan(username):
    log(f"Starting auto-scan for @{username}")

    try:
        L = get_loader()
        if not L.test_login() and not L.context.is_logged_in:
            log("ERROR: No valid session. Reconnect via the web UI.")
            return False

        # 1. Profile
        log("Scraping profile...")
        profile_obj = scrape_profile(L, username, OUTPUT_DIR)
        with open(Path(OUTPUT_DIR) / username / "profile.json") as f:
            profile_data = json.load(f)

        if profile_obj.is_private and not profile_obj.followed_by_viewer:
            log("ERROR: Profile is private")
            return False

        # 2. Followers + snapshot (for unfollower tracking)
        log("Scraping followers...")
        followers = scrape_followers(L, profile_obj, OUTPUT_DIR)
        if followers:
            save_follower_snapshot(followers, username, OUTPUT_DIR)
            log(f"Saved snapshot: {len(followers)} followers")

            # Compare with previous
            snapshots = load_follower_snapshots(username, OUTPUT_DIR)
            if len(snapshots) >= 2:
                comparison = compare_follower_snapshots(snapshots[-2], snapshots[-1])
                unfollower_analysis = analyze_unfollowers(comparison["unfollowers"])
                new_follower_analysis = analyze_unfollowers(comparison["new_followers"])

                history = []
                for i in range(1, len(snapshots)):
                    comp = compare_follower_snapshots(snapshots[i - 1], snapshots[i])
                    history.append({
                        "from": comp["old_timestamp"], "to": comp["new_timestamp"],
                        "unfollower_count": comp["unfollower_count"],
                        "new_follower_count": comp["new_follower_count"],
                        "net_change": comp["net_change"],
                        "old_count": comp["old_count"], "new_count": comp["new_count"],
                    })

                report = {
                    "username": username,
                    "profile_follower_count": profile_data.get("followers", 0),
                    "snapshot_count": len(snapshots),
                    "latest_snapshot": {"timestamp": snapshots[-1]["timestamp"], "count": snapshots[-1]["count"]},
                    "login_required": False,
                    "comparison": comparison,
                    "unfollower_analysis": unfollower_analysis,
                    "new_follower_analysis": new_follower_analysis,
                    "history": history,
                }
                with open(Path(OUTPUT_DIR) / username / "unfollowers.json", "w") as f:
                    json.dump(report, f, indent=2, default=str)
                log(f"Unfollower report: {comparison['unfollower_count']} unfollowed, {comparison['new_follower_count']} new")

        # 3. Following + relationships
        log("Scraping following...")
        following = scrape_following(L, profile_obj, OUTPUT_DIR)
        if followers and following:
            rel_report = analyze_follow_relationship(followers, following)
            rel_report["username"] = username
            rel_report["analyzed_at"] = datetime.now().isoformat()
            with open(Path(OUTPUT_DIR) / username / "relationships.json", "w") as f:
                json.dump(rel_report, f, indent=2, default=str)
            log(f"Relationships: {rel_report['fans_count']} fans, {rel_report['not_following_back_count']} don't follow back")

        # 4. Posts + content advisor
        log("Scraping posts...")
        posts_data = scrape_posts(L, profile_obj, OUTPUT_DIR, limit=50, download_media=False)
        snapshots_meta = [{"timestamp": s["timestamp"], "count": s["count"]}
                          for s in load_follower_snapshots(username, OUTPUT_DIR)]
        advisor_report = analyze_content_performance(posts_data, profile_data, snapshots_meta or None)
        advisor_report["username"] = username
        advisor_report["analyzed_at"] = datetime.now().isoformat()
        advisor_report["posts_analyzed"] = len(posts_data)
        advisor_report["followers"] = profile_data.get("followers", 0)
        with open(Path(OUTPUT_DIR) / username / "advisor.json", "w") as f:
            json.dump(advisor_report, f, indent=2, default=str)
        log(f"Advisor report: {len(advisor_report.get('recommendations', []))} recommendations")

        # 5. Story viewers (if any active stories)
        log("Checking story viewers...")
        try:
            scrape_story_viewers(L, profile_obj, OUTPUT_DIR)
        except Exception as e:
            log(f"Story viewers skipped: {e}")

        log(f"Auto-scan complete for @{username}")
        return True

    except Exception as e:
        log(f"ERROR: {e}")
        return False


if __name__ == "__main__":
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    log("=" * 50)
    log("Auto-scan started")

    for user in USERS:
        run_scan(user)

    log("Auto-scan finished")
    log("=" * 50)
