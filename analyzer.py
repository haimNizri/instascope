#!/usr/bin/env python3
"""
Instagram Profile Analyzer — authenticity scoring, engagement analysis,
campaign detection, and demographic estimation from scraped data.

Usage:
    python3 analyzer.py onepromiseaday [--deep -u USER -p PASS]
"""

import argparse
import json
import os
import re
import sys
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import instaloader

# ── Gender estimation from first names ───────────────────────────────────────
# Common name → gender mappings (expandable)
FEMALE_NAMES = {
    "maria", "anna", "emma", "sarah", "laura", "sofia", "sophie", "jessica",
    "jennifer", "ashley", "amanda", "stephanie", "nicole", "melissa", "lisa",
    "amy", "mary", "patricia", "linda", "elizabeth", "barbara", "susan",
    "margaret", "dorothy", "karen", "nancy", "betty", "helen", "sandra",
    "donna", "carol", "ruth", "sharon", "michelle", "emily", "rachel",
    "julia", "megan", "hannah", "natalie", "victoria", "olivia", "isabella",
    "mia", "charlotte", "amelia", "harper", "ella", "grace", "chloe", "zoey",
    "lily", "scarlett", "aria", "layla", "riley", "nora", "camila", "elena",
    "valentina", "luna", "gabriella", "naomi", "alice", "madelyn", "stella",
    "eva", "emilia", "violet", "aurora", "hazel", "ivy", "ellie", "paisley",
    "audrey", "claire", "bella", "lucy", "savannah", "caroline", "genesis",
    "aaliyah", "kennedy", "kinsley", "allison", "maya", "leah", "madeline",
    "alexa", "ariana", "fatima", "aisha", "priya", "ananya", "deepika",
    "pooja", "neha", "shreya", "riya", "divya", "kavita", "sunita", "meera",
    "sara", "lara", "nina", "diana", "rosa", "carmen", "lucia", "paula",
    "andrea", "claudia", "silvia", "giulia", "chiara", "francesca", "elena",
    "marie", "sophie", "camille", "julie", "manon", "lea", "chloe", "emma",
    "lina", "hana", "yuki", "sakura", "mei", "yuna", "seo", "min", "ji",
}

MALE_NAMES = {
    "james", "john", "robert", "michael", "david", "william", "richard",
    "joseph", "thomas", "charles", "christopher", "daniel", "matthew",
    "anthony", "mark", "donald", "steven", "paul", "andrew", "joshua",
    "kenneth", "kevin", "brian", "george", "timothy", "ronald", "edward",
    "jason", "jeffrey", "ryan", "jacob", "gary", "nicholas", "eric",
    "jonathan", "stephen", "larry", "justin", "scott", "brandon", "benjamin",
    "samuel", "raymond", "gregory", "frank", "alexander", "patrick", "jack",
    "dennis", "jerry", "tyler", "aaron", "jose", "adam", "nathan", "henry",
    "peter", "zachary", "douglas", "harold", "carl", "arthur", "gerald",
    "roger", "keith", "jeremy", "lawrence", "terry", "sean", "albert",
    "joe", "christian", "austin", "jesse", "ethan", "noah", "liam", "mason",
    "logan", "lucas", "oliver", "elijah", "aiden", "jackson", "sebastian",
    "owen", "gabriel", "carter", "jayden", "luke", "dylan", "grayson",
    "leo", "isaac", "lincoln", "jaxon", "asher", "maverick", "josiah",
    "hudson", "ezra", "muhammad", "ahmed", "ali", "omar", "hassan",
    "hussein", "mohammad", "ibrahim", "youssef", "khalid", "raj", "amit",
    "rahul", "vikram", "arjun", "rohit", "sanjay", "vijay", "suresh",
    "carlos", "miguel", "diego", "pedro", "luis", "jorge", "pablo",
    "marco", "luca", "matteo", "alessandro", "lorenzo", "pierre", "jean",
    "louis", "hugo", "theo", "lucas", "leo", "kenji", "hiroshi", "takeshi",
}


def guess_gender(full_name):
    """Guess gender from first name. Returns 'female', 'male', or 'unknown'."""
    if not full_name:
        return "unknown"
    first = full_name.strip().split()[0].lower().strip("._-0123456789")
    if first in FEMALE_NAMES:
        return "female"
    if first in MALE_NAMES:
        return "male"
    # heuristic: names ending in 'a' are more often female in many languages
    if len(first) > 2 and first.endswith("a") and first not in {"joshua", "ezra", "luca", "nicola"}:
        return "likely_female"
    return "unknown"


# ── Authenticity signals ─────────────────────────────────────────────────────

def analyze_authenticity(profile_data, posts_data, followers_sample=None):
    """Score profile authenticity on a 0-100 scale."""
    score = 100
    flags = []
    positives = []

    followers = profile_data.get("followers", 0)
    following = profile_data.get("following", 0)
    posts_count = profile_data.get("posts_count", 0)

    # 1. Follower/following ratio
    if followers > 0 and following > 0:
        ratio = followers / following
        if ratio < 0.1:
            score -= 20
            flags.append(f"Very low follower/following ratio ({ratio:.2f}) — possible follow-for-follow")
        elif ratio > 100 and not profile_data.get("is_verified"):
            score -= 10
            flags.append(f"Extremely high ratio ({ratio:.0f}) — unusual for non-verified")
        else:
            positives.append(f"Healthy follower/following ratio ({ratio:.1f})")

    # 2. Posts count vs followers
    if posts_count > 0 and followers > 0:
        followers_per_post = followers / posts_count
        if followers_per_post > 10000 and not profile_data.get("is_verified"):
            score -= 10
            flags.append(f"Very high followers-per-post ({followers_per_post:.0f}) — may have bought followers")

    # 3. Engagement rate from posts
    if posts_data:
        engagement_rates = []
        for p in posts_data:
            likes = p.get("likes", 0)
            comments = p.get("comments_count", 0)
            if likes > 0 and followers > 0:
                er = ((likes + comments) / followers) * 100
                engagement_rates.append(er)

        if engagement_rates:
            avg_er = statistics.mean(engagement_rates)
            if avg_er < 0.5:
                score -= 15
                flags.append(f"Very low engagement rate ({avg_er:.2f}%) — possible fake followers")
            elif avg_er > 10:
                score -= 10
                flags.append(f"Unusually high engagement ({avg_er:.1f}%) — possible engagement pods")
            elif avg_er >= 1.0:
                positives.append(f"Good engagement rate ({avg_er:.2f}%)")
            else:
                positives.append(f"Average engagement rate ({avg_er:.2f}%)")

            # Engagement consistency
            if len(engagement_rates) >= 3:
                er_std = statistics.stdev(engagement_rates)
                er_cv = er_std / avg_er if avg_er > 0 else 0
                if er_cv > 2:
                    score -= 10
                    flags.append(f"Highly inconsistent engagement (CV={er_cv:.1f}) — possible bought engagement on select posts")
                else:
                    positives.append(f"Consistent engagement pattern (CV={er_cv:.1f})")

    # 4. Posting frequency
    if posts_data and len(posts_data) >= 2:
        dates = sorted([datetime.fromisoformat(p["date"]) for p in posts_data if p.get("date")])
        if len(dates) >= 2:
            gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
            avg_gap = statistics.mean([abs(g) for g in gaps])
            if avg_gap < 0.1:
                score -= 15
                flags.append("Bulk posting detected — posts within minutes of each other")
            else:
                positives.append(f"Normal posting frequency (avg {avg_gap:.0f} days between posts)")

    # 5. Bio and profile completeness
    if profile_data.get("biography"):
        positives.append("Has biography")
    else:
        score -= 5
        flags.append("Empty biography")

    if profile_data.get("full_name"):
        positives.append("Has full name")
    else:
        score -= 5
        flags.append("No full name set")

    if profile_data.get("is_verified"):
        score += 10  # can go above 100, we cap later
        positives.append("Verified account")

    if profile_data.get("external_url"):
        positives.append("Has external URL")

    # 6. Follower quality (if sample available)
    if followers_sample:
        no_name = sum(1 for f in followers_sample if not f.get("full_name"))
        private = sum(1 for f in followers_sample if f.get("is_private"))
        no_name_pct = (no_name / len(followers_sample)) * 100
        private_pct = (private / len(followers_sample)) * 100

        if no_name_pct > 50:
            score -= 15
            flags.append(f"{no_name_pct:.0f}% of sampled followers have no name — bot indicator")
        if private_pct > 80:
            score -= 5
            flags.append(f"{private_pct:.0f}% of sampled followers are private — unusual concentration")
        else:
            positives.append(f"Follower quality looks normal ({no_name_pct:.0f}% nameless, {private_pct:.0f}% private)")

    score = max(0, min(100, score))

    if score >= 80:
        verdict = "LIKELY REAL"
    elif score >= 60:
        verdict = "MOSTLY REAL (some concerns)"
    elif score >= 40:
        verdict = "SUSPICIOUS"
    else:
        verdict = "LIKELY FAKE"

    return {
        "authenticity_score": score,
        "verdict": verdict,
        "positive_signals": positives,
        "red_flags": flags,
    }


# ── Demographics estimation ──────────────────────────────────────────────────

def estimate_demographics(followers_sample):
    """Estimate gender and geography from a follower sample."""
    genders = Counter()
    countries = Counter()
    languages = Counter()

    for f in followers_sample:
        # Gender from name
        g = guess_gender(f.get("full_name", ""))
        if g == "likely_female":
            genders["female"] += 0.7
            genders["unknown"] += 0.3
        else:
            genders[g] += 1

        # Try to extract location/language hints from username patterns
        username = f.get("username", "")
        # Common country-code patterns in usernames
        for code, country in [("_br", "Brazil"), ("_tr", "Turkey"), ("_id", "Indonesia"),
                              ("_in", "India"), ("_mx", "Mexico"), ("_ru", "Russia"),
                              ("_it", "Italy"), ("_fr", "France"), ("_de", "Germany"),
                              ("_jp", "Japan"), ("_kr", "Korea"), ("_ar", "Argentina"),
                              ("_es", "Spain"), ("_uk", "UK"), ("_us", "USA"),
                              ("_ph", "Philippines"), ("_ir", "Iran"), ("_eg", "Egypt")]:
            if username.endswith(code) or code + "_" in username:
                countries[country] += 1

    total = len(followers_sample)
    gender_dist = {}
    for g in ["female", "male", "unknown"]:
        count = genders.get(g, 0)
        gender_dist[g] = {
            "count": round(count),
            "percentage": round((count / total) * 100, 1) if total > 0 else 0
        }

    return {
        "sample_size": total,
        "gender_distribution": gender_dist,
        "detected_countries": dict(countries.most_common(15)),
        "note": "Demographics are estimated from name analysis and username patterns. Actual demographics may vary.",
    }


# ── Age estimation (from content analysis) ───────────────────────────────────

def estimate_audience_age(posts_data, profile_data):
    """Estimate likely audience age range from content themes and hashtags."""
    all_hashtags = []
    all_captions = []
    for p in posts_data:
        all_hashtags.extend([h.lower() for h in p.get("hashtags", [])])
        if p.get("caption"):
            all_captions.append(p["caption"].lower())

    combined_text = " ".join(all_captions)
    hashtag_set = set(all_hashtags)

    age_signals = {
        "13-17": 0, "18-24": 0, "25-34": 0, "35-44": 0, "45-54": 0, "55+": 0
    }

    # Content theme → age mapping
    young_keywords = {"tiktok", "viral", "fyp", "gen z", "genz", "stan", "bestie", "slay", "era", "aesthetic"}
    young_adult = {"startup", "hustle", "grind", "entrepreneur", "selfcare", "wellness", "brunch", "travel"}
    mid_adult = {"business", "leadership", "ceo", "founder", "parenting", "mortgage", "career", "investment"}
    mature_keywords = {"retirement", "grandchildren", "legacy", "wisdom", "classic"}

    for kw in young_keywords:
        if kw in combined_text or kw in hashtag_set:
            age_signals["13-17"] += 1
            age_signals["18-24"] += 2

    for kw in young_adult:
        if kw in combined_text or kw in hashtag_set:
            age_signals["18-24"] += 1
            age_signals["25-34"] += 2

    for kw in mid_adult:
        if kw in combined_text or kw in hashtag_set:
            age_signals["25-34"] += 1
            age_signals["35-44"] += 2
            age_signals["45-54"] += 1

    for kw in mature_keywords:
        if kw in combined_text or kw in hashtag_set:
            age_signals["45-54"] += 1
            age_signals["55+"] += 2

    # Normalize to percentages
    total_signals = sum(age_signals.values())
    if total_signals == 0:
        # Default distribution based on Instagram averages
        return {
            "estimated_age_distribution": {
                "13-17": "5%", "18-24": "30%", "25-34": "35%",
                "35-44": "20%", "45-54": "7%", "55+": "3%"
            },
            "primary_age_group": "25-34",
            "method": "Instagram platform average (insufficient content signals)",
        }

    age_dist = {}
    for bracket, count in age_signals.items():
        age_dist[bracket] = f"{(count / total_signals * 100):.0f}%"

    primary = max(age_signals, key=age_signals.get)

    return {
        "estimated_age_distribution": age_dist,
        "primary_age_group": primary,
        "method": "Content and hashtag theme analysis",
    }


# ── Campaign / sponsored content detection ───────────────────────────────────

def detect_campaigns(posts_data):
    """Detect potential brand campaigns and sponsored content."""
    sponsored_indicators = [
        "ad", "sponsored", "partner", "collab", "gifted", "paid",
        "ambassador", "promo", "discount", "code", "link in bio",
        "use my code", "swipe up", "shop now", "available at",
        "collaboration", "partnership",
    ]

    campaigns = []
    brand_mentions = Counter()
    hashtag_freq = Counter()
    posting_calendar = defaultdict(int)

    for p in posts_data:
        caption = (p.get("caption") or "").lower()
        hashtags = [h.lower() for h in p.get("hashtags", [])]
        mentions = p.get("mentions", [])
        date = p.get("date", "")

        # Track hashtag frequency
        for h in hashtags:
            hashtag_freq[h] += 1

        # Track mentions
        for m in mentions:
            brand_mentions[m] += 1

        # Track posting by month
        if date:
            month = date[:7]
            posting_calendar[month] += 1

        # Detect sponsored content
        is_sponsored = False
        sponsor_signals = []
        for indicator in sponsored_indicators:
            if indicator in caption:
                is_sponsored = True
                sponsor_signals.append(indicator)

        # #ad in hashtags
        if "ad" in hashtags or "sponsored" in hashtags or "partner" in hashtags:
            is_sponsored = True
            sponsor_signals.append("hashtag disclosure")

        if is_sponsored:
            campaigns.append({
                "post": p.get("shortcode"),
                "date": date,
                "signals": sponsor_signals,
                "mentions": mentions,
                "caption_preview": (p.get("caption") or "")[:100] + "...",
            })

    # Detect recurring brand partnerships (mentioned 2+ times)
    recurring_brands = {k: v for k, v in brand_mentions.items() if v >= 2}

    return {
        "sponsored_posts_detected": len(campaigns),
        "total_posts_analyzed": len(posts_data),
        "sponsorship_rate": f"{(len(campaigns)/len(posts_data)*100):.1f}%" if posts_data else "0%",
        "sponsored_posts": campaigns,
        "recurring_brand_partners": dict(brand_mentions.most_common(10)),
        "top_hashtags": dict(hashtag_freq.most_common(20)),
        "posting_calendar": dict(sorted(posting_calendar.items())),
    }


# ── Business insights ────────────────────────────────────────────────────────

def business_insights(profile_data, posts_data):
    """Generate business-relevant insights."""
    followers = profile_data.get("followers", 0)

    # Engagement metrics
    likes_list = [p["likes"] for p in posts_data if p.get("likes", 0) > 0]
    comments_list = [p["comments_count"] for p in posts_data if p.get("comments_count", 0) > 0]

    avg_likes = statistics.mean(likes_list) if likes_list else 0
    avg_comments = statistics.mean(comments_list) if comments_list else 0
    avg_engagement = ((avg_likes + avg_comments) / followers * 100) if followers > 0 and avg_likes > 0 else None

    # Content type breakdown
    types = Counter(p.get("typename", "unknown") for p in posts_data)

    # Best performing posts
    best_by_likes = sorted([p for p in posts_data if p.get("likes", 0) > 0],
                           key=lambda x: x.get("likes", 0), reverse=True)[:3]
    best_by_comments = sorted(posts_data, key=lambda x: x.get("comments_count", 0), reverse=True)[:3]

    # Video performance
    videos = [p for p in posts_data if p.get("is_video")]
    images = [p for p in posts_data if not p.get("is_video")]

    video_avg_views = statistics.mean([p.get("video_view_count", 0) for p in videos if p.get("video_view_count")]) if videos else 0

    # Posting frequency
    dates = sorted([datetime.fromisoformat(p["date"]) for p in posts_data if p.get("date")])
    if len(dates) >= 2:
        span_days = (dates[-1] - dates[0]).days or 1
        posts_per_week = len(dates) / (span_days / 7)
    else:
        posts_per_week = 0

    # Day of week distribution
    day_dist = Counter()
    hour_dist = Counter()
    for p in posts_data:
        if p.get("date"):
            dt = datetime.fromisoformat(p["date"])
            day_dist[dt.strftime("%A")] += 1
            hour_dist[dt.hour] += 1

    best_day = day_dist.most_common(1)[0] if day_dist else ("Unknown", 0)
    best_hours = hour_dist.most_common(3) if hour_dist else []

    # Estimated value
    if avg_engagement and avg_engagement > 0:
        # rough CPM-based estimation
        if followers < 10000:
            est_per_post = "$50 - $250"
            tier = "Nano influencer"
        elif followers < 50000:
            est_per_post = "$250 - $1,000"
            tier = "Micro influencer"
        elif followers < 500000:
            est_per_post = "$1,000 - $5,000"
            tier = "Mid-tier influencer"
        elif followers < 1000000:
            est_per_post = "$5,000 - $15,000"
            tier = "Macro influencer"
        else:
            est_per_post = "$15,000+"
            tier = "Mega influencer"
    else:
        est_per_post = "N/A"
        tier = "Unknown"

    return {
        "account_tier": tier,
        "followers": followers,
        "avg_likes": round(avg_likes),
        "avg_comments": round(avg_comments),
        "avg_engagement_rate": f"{avg_engagement:.2f}%" if avg_engagement else "N/A (likes hidden)",
        "estimated_post_value": est_per_post,
        "content_mix": dict(types),
        "videos_count": len(videos),
        "images_count": len(images),
        "avg_video_views": round(video_avg_views),
        "posts_per_week": round(posts_per_week, 1),
        "best_posting_day": best_day[0] if best_day else "Unknown",
        "best_posting_hours_utc": [f"{h[0]}:00" for h in best_hours],
        "top_posts_by_likes": [{"shortcode": p["shortcode"], "likes": p["likes"]} for p in best_by_likes],
        "top_posts_by_comments": [{"shortcode": p["shortcode"], "comments": p["comments_count"]} for p in best_by_comments],
    }


# ── Report printer ───────────────────────────────────────────────────────────

def print_report(report):
    """Pretty print the analysis report."""

    def section(title):
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")

    # Header
    p = report["profile"]
    section(f"INSTAGRAM ANALYSIS: @{p['username']}")
    print(f"  {p.get('full_name', '')} | {p['followers']:,} followers | {p['posts_count']} posts")
    if p.get("is_verified"):
        print("  [VERIFIED]")

    # Authenticity
    auth = report["authenticity"]
    section(f"AUTHENTICITY SCORE: {auth['authenticity_score']}/100 — {auth['verdict']}")
    if auth["positive_signals"]:
        print("\n  Positive signals:")
        for s in auth["positive_signals"]:
            print(f"    [+] {s}")
    if auth["red_flags"]:
        print("\n  Red flags:")
        for f in auth["red_flags"]:
            print(f"    [!] {f}")

    # Demographics
    if "demographics" in report:
        demo = report["demographics"]
        section(f"DEMOGRAPHICS (sample: {demo['sample_size']})")
        gd = demo["gender_distribution"]
        print(f"\n  Gender split:")
        print(f"    Female:  {gd.get('female', {}).get('percentage', 0)}%")
        print(f"    Male:    {gd.get('male', {}).get('percentage', 0)}%")
        print(f"    Unknown: {gd.get('unknown', {}).get('percentage', 0)}%")
        if demo.get("detected_countries"):
            print(f"\n  Detected countries (from username patterns):")
            for country, count in demo["detected_countries"].items():
                print(f"    {country}: {count}")

    # Age
    age = report["audience_age"]
    section("ESTIMATED AUDIENCE AGE")
    print(f"  Method: {age['method']}")
    print(f"  Primary age group: {age['primary_age_group']}")
    for bracket, pct in age["estimated_age_distribution"].items():
        bar = "#" * max(1, int(float(pct.strip('%')) / 3))
        print(f"    {bracket:>5}: {pct:>4} {bar}")

    # Campaigns
    camp = report["campaigns"]
    section("CAMPAIGN & SPONSORSHIP ANALYSIS")
    print(f"  Sponsored posts detected: {camp['sponsored_posts_detected']}/{camp['total_posts_analyzed']}")
    print(f"  Sponsorship rate: {camp['sponsorship_rate']}")
    if camp["recurring_brand_partners"]:
        print(f"\n  Brand partners (by mentions):")
        for brand, count in camp["recurring_brand_partners"].items():
            print(f"    @{brand}: {count} mentions")
    if camp["top_hashtags"]:
        print(f"\n  Top hashtags:")
        for tag, count in list(camp["top_hashtags"].items())[:10]:
            print(f"    #{tag}: {count}")

    # Business
    biz = report["business_insights"]
    section("BUSINESS INSIGHTS")
    print(f"  Account tier:         {biz['account_tier']}")
    print(f"  Avg likes:            {biz['avg_likes']:,}")
    print(f"  Avg comments:         {biz['avg_comments']}")
    print(f"  Avg engagement rate:  {biz['avg_engagement_rate']}")
    print(f"  Est. post value:      {biz['estimated_post_value']}")
    print(f"  Posts/week:           {biz['posts_per_week']}")
    print(f"  Content mix:          {biz['content_mix']}")
    print(f"  Avg video views:      {biz['avg_video_views']:,}")
    print(f"  Best posting day:     {biz['best_posting_day']}")
    print(f"  Best posting hours:   {', '.join(biz['best_posting_hours_utc'])} UTC")

    section("END OF REPORT")
    print()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Instagram Profile Analyzer")
    parser.add_argument("target", help="Username to analyze")
    parser.add_argument("-o", "--output", default="output", help="Data directory")
    parser.add_argument("--deep", action="store_true",
                        help="Deep analysis: scrape followers for demographics (requires login)")
    parser.add_argument("-u", "--username", help="Your Instagram username")
    parser.add_argument("-p", "--password", help="Your Instagram password")
    parser.add_argument("--follower-sample", type=int, default=200,
                        help="Number of followers to sample for demographics (default: 200)")
    parser.add_argument("--post-limit", type=int, default=50,
                        help="Max posts to analyze (default: 50)")

    args = parser.parse_args()
    target = args.target
    output_dir = args.output

    # Load or scrape profile
    profile_path = Path(output_dir) / target / "profile.json"
    posts_path = Path(output_dir) / target / "posts.json"

    from scraper import get_loader, scrape_profile, scrape_posts

    L = get_loader(args.username, args.password)

    # Always fresh-scrape profile
    print(f"[*] Fetching profile: {target}")
    profile_obj = scrape_profile(L, target, output_dir)

    with open(profile_path) as f:
        profile_data = json.load(f)

    if profile_obj.is_private and not profile_obj.followed_by_viewer:
        print("[!] Profile is private — can only analyze profile info")
        print("[!] Log in with an account that follows this user for full analysis")
        auth = analyze_authenticity(profile_data, [])
        report = {
            "profile": profile_data,
            "authenticity": auth,
            "audience_age": estimate_audience_age([], profile_data),
            "campaigns": {"sponsored_posts_detected": 0, "total_posts_analyzed": 0,
                         "sponsorship_rate": "N/A", "sponsored_posts": [],
                         "recurring_brand_partners": {}, "top_hashtags": {}, "posting_calendar": {}},
            "business_insights": business_insights(profile_data, []),
        }
        print_report(report)
        save_path = Path(output_dir) / target / "analysis.json"
        with open(save_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"[+] Report saved to {save_path}")
        return

    # Scrape posts
    if not posts_path.exists():
        print(f"[*] Scraping posts (limit: {args.post_limit})...")
        scrape_posts(L, profile_obj, output_dir, limit=args.post_limit, download_media=False)

    with open(posts_path) as f:
        posts_data = json.load(f)

    # Deep mode: sample followers
    followers_sample = None
    if args.deep:
        followers_path = Path(output_dir) / target / "followers_sample.json"
        print(f"[*] Sampling {args.follower_sample} followers for demographics...")
        sample = []
        try:
            for i, follower in enumerate(profile_obj.get_followers()):
                if i >= args.follower_sample:
                    break
                sample.append({
                    "username": follower.username,
                    "full_name": follower.full_name,
                    "is_private": follower.is_private,
                    "is_verified": follower.is_verified,
                })
                if (i + 1) % 50 == 0:
                    print(f"  ... {i+1} followers sampled")
        except Exception as e:
            print(f"[!] Stopped sampling at {len(sample)}: {e}")

        if sample:
            with open(followers_path, "w") as f:
                json.dump(sample, f, indent=2)
            followers_sample = sample
            print(f"[+] Sampled {len(sample)} followers")

    # Run analysis
    print("\n[*] Running analysis...")

    auth = analyze_authenticity(profile_data, posts_data, followers_sample)
    age = estimate_audience_age(posts_data, profile_data)
    campaigns = detect_campaigns(posts_data)
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

    # Print and save
    print_report(report)

    save_path = Path(output_dir) / target / "analysis.json"
    with open(save_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"[+] Full report saved to {save_path}")


def analyze_follow_relationship(followers_list, following_list):
    """Compare followers vs following to find fans and non-followers-back."""
    follower_map = {f["username"]: f for f in followers_list}
    following_map = {f["username"]: f for f in following_list}

    follower_usernames = set(follower_map.keys())
    following_usernames = set(following_map.keys())

    # People who follow me but I don't follow back (fans)
    fans_usernames = follower_usernames - following_usernames
    fans = []
    for u in sorted(fans_usernames):
        info = follower_map[u]
        g = guess_gender(info.get("full_name", ""))
        fans.append({
            "username": u,
            "full_name": info.get("full_name", ""),
            "gender": g if g != "likely_female" else "female",
            "is_private": info.get("is_private", False),
            "is_verified": info.get("is_verified", False),
        })

    # People I follow but don't follow me back
    not_following_back_usernames = following_usernames - follower_usernames
    not_following_back = []
    for u in sorted(not_following_back_usernames):
        info = following_map[u]
        g = guess_gender(info.get("full_name", ""))
        not_following_back.append({
            "username": u,
            "full_name": info.get("full_name", ""),
            "gender": g if g != "likely_female" else "female",
            "is_private": info.get("is_private", False),
            "is_verified": info.get("is_verified", False),
        })

    # Mutual follows
    mutual_usernames = follower_usernames & following_usernames
    mutual = []
    for u in sorted(mutual_usernames):
        info = follower_map[u]
        g = guess_gender(info.get("full_name", ""))
        mutual.append({
            "username": u,
            "full_name": info.get("full_name", ""),
            "gender": g if g != "likely_female" else "female",
            "is_private": info.get("is_private", False),
            "is_verified": info.get("is_verified", False),
        })

    # Gender stats helper
    def gender_stats(profiles):
        genders = Counter()
        for p in profiles:
            genders[p.get("gender", "unknown")] += 1
        total = len(profiles)
        return {
            g: {"count": c, "percentage": round(c / total * 100, 1) if total > 0 else 0}
            for g, c in [("female", genders.get("female", 0)),
                         ("male", genders.get("male", 0)),
                         ("unknown", genders.get("unknown", 0))]
        }

    return {
        "followers_count": len(followers_list),
        "following_count": len(following_list),
        "mutual_count": len(mutual),
        "fans": fans,
        "fans_count": len(fans),
        "fans_gender": gender_stats(fans) if fans else {},
        "not_following_back": not_following_back,
        "not_following_back_count": len(not_following_back),
        "not_following_back_gender": gender_stats(not_following_back) if not_following_back else {},
        "mutual": mutual,
        "mutual_gender": gender_stats(mutual) if mutual else {},
    }


def analyze_content_performance(posts_data, profile_data, follower_snapshots=None):
    """Analyze content performance and generate actionable recommendations."""
    followers = profile_data.get("followers", 0)
    if not posts_data or followers == 0:
        return {
            "best_hours": [],
            "best_day": None,
            "content_type_performance": {},
            "hashtag_performance": {"top": [], "bottom": []},
            "caption_length_performance": {},
            "engagement_trend": [],
            "recommendations": ["Not enough data to generate recommendations."],
            "follower_correlation": None,
        }

    # Helper: engagement rate for a post
    def post_er(p):
        return ((p.get("likes", 0) + p.get("comments_count", 0)) / followers) * 100

    # ── 1. Best posting times ────────────────────────────────────────────────
    hour_engagement = defaultdict(list)
    day_engagement = defaultdict(list)
    for p in posts_data:
        if not p.get("date"):
            continue
        dt = datetime.fromisoformat(p["date"])
        er = post_er(p)
        hour_engagement[dt.hour].append(er)
        day_engagement[dt.strftime("%A")].append(er)

    hour_avg = {h: statistics.mean(rates) for h, rates in hour_engagement.items()}
    day_avg = {d: statistics.mean(rates) for d, rates in day_engagement.items()}

    best_hours = sorted(hour_avg.items(), key=lambda x: x[1], reverse=True)[:3]
    best_hours = [{"hour": h, "avg_engagement": round(er, 3)} for h, er in best_hours]

    best_day = max(day_avg.items(), key=lambda x: x[1]) if day_avg else None
    best_day_result = {"day": best_day[0], "avg_engagement": round(best_day[1], 3)} if best_day else None

    # ── 2. Content type performance ──────────────────────────────────────────
    type_data = defaultdict(lambda: {"likes": [], "comments": [], "er": []})
    for p in posts_data:
        typename = p.get("typename", "unknown")
        type_data[typename]["likes"].append(p.get("likes", 0))
        type_data[typename]["comments"].append(p.get("comments_count", 0))
        type_data[typename]["er"].append(post_er(p))

    content_type_performance = {}
    for typename, data in type_data.items():
        content_type_performance[typename] = {
            "count": len(data["likes"]),
            "avg_likes": round(statistics.mean(data["likes"]), 1),
            "avg_comments": round(statistics.mean(data["comments"]), 1),
            "avg_engagement_rate": round(statistics.mean(data["er"]), 3),
        }

    # ── 3. Hashtag performance ───────────────────────────────────────────────
    hashtag_er = defaultdict(list)
    for p in posts_data:
        er = post_er(p)
        for tag in p.get("hashtags", []):
            hashtag_er[tag.lower()].append(er)

    hashtag_avg = {tag: statistics.mean(rates) for tag, rates in hashtag_er.items()}
    sorted_hashtags = sorted(hashtag_avg.items(), key=lambda x: x[1], reverse=True)

    top_hashtags = [{"hashtag": tag, "avg_engagement": round(er, 3), "post_count": len(hashtag_er[tag])}
                    for tag, er in sorted_hashtags[:15]]
    bottom_hashtags = [{"hashtag": tag, "avg_engagement": round(er, 3), "post_count": len(hashtag_er[tag])}
                       for tag, er in sorted_hashtags[-5:]] if len(sorted_hashtags) > 5 else []

    # ── 4. Post length analysis ──────────────────────────────────────────────
    length_buckets = {"short": (0, 50), "medium": (51, 150), "long": (151, 300), "very_long": (301, float("inf"))}
    bucket_er = {name: [] for name in length_buckets}
    for p in posts_data:
        caption_len = len(p.get("caption") or "")
        er = post_er(p)
        for name, (lo, hi) in length_buckets.items():
            if lo <= caption_len <= hi:
                bucket_er[name].append(er)
                break

    caption_length_performance = {}
    for name, rates in bucket_er.items():
        if rates:
            caption_length_performance[name] = {
                "post_count": len(rates),
                "avg_engagement": round(statistics.mean(rates), 3),
            }
        else:
            caption_length_performance[name] = {"post_count": 0, "avg_engagement": 0}

    # ── 5. Engagement trend ──────────────────────────────────────────────────
    month_er = defaultdict(list)
    for p in posts_data:
        if not p.get("date"):
            continue
        month_key = p["date"][:7]  # YYYY-MM
        month_er[month_key].append(post_er(p))

    engagement_trend = sorted([
        {"month": m, "avg_engagement": round(statistics.mean(rates), 3)}
        for m, rates in month_er.items()
    ], key=lambda x: x["month"])

    # ── 7. Follower impact / correlation ─────────────────────────────────────
    follower_correlation = None
    if follower_snapshots and len(follower_snapshots) >= 2:
        correlations = []
        for i in range(len(follower_snapshots) - 1):
            snap_a = follower_snapshots[i]
            snap_b = follower_snapshots[i + 1]
            ts_a = datetime.fromisoformat(snap_a["timestamp"]) if isinstance(snap_a["timestamp"], str) else snap_a["timestamp"]
            ts_b = datetime.fromisoformat(snap_b["timestamp"]) if isinstance(snap_b["timestamp"], str) else snap_b["timestamp"]
            follower_change = snap_b["count"] - snap_a["count"]

            # Find posts published between the two snapshots
            period_posts = []
            for p in posts_data:
                if not p.get("date"):
                    continue
                pdt = datetime.fromisoformat(p["date"])
                if ts_a <= pdt <= ts_b:
                    period_posts.append(p)

            if period_posts:
                avg_er_period = statistics.mean([post_er(p) for p in period_posts])
            else:
                avg_er_period = 0

            correlations.append({
                "period_start": str(ts_a.date()),
                "period_end": str(ts_b.date()),
                "follower_change": follower_change,
                "posts_in_period": len(period_posts),
                "avg_engagement_in_period": round(avg_er_period, 3),
                "high_engagement_correlated_with_growth": avg_er_period > 0 and follower_change > 0,
            })
        follower_correlation = correlations

    # ── 6. Content recommendations ───────────────────────────────────────────
    recommendations = []

    # Best time to post
    if best_hours and best_day_result:
        best_h = best_hours[0]["hour"]
        h_start = best_h
        h_end = best_h + 2 if best_h + 2 <= 23 else 23
        recommendations.append(
            f"Post between {h_start}:00-{h_end}:00 UTC on {best_day_result['day']}s for highest engagement"
        )

    # Best content type
    if len(content_type_performance) > 1:
        best_type = max(content_type_performance.items(), key=lambda x: x[1]["avg_engagement_rate"])
        worst_type = min(content_type_performance.items(), key=lambda x: x[1]["avg_engagement_rate"])
        if worst_type[1]["avg_engagement_rate"] > 0:
            ratio = best_type[1]["avg_engagement_rate"] / worst_type[1]["avg_engagement_rate"]
            type_labels = {"GraphImage": "single images", "GraphVideo": "videos", "GraphSidecar": "carousels"}
            best_label = type_labels.get(best_type[0], best_type[0])
            worst_label = type_labels.get(worst_type[0], worst_type[0])
            recommendations.append(
                f"{best_label.capitalize()} get {ratio:.1f}x more engagement than {worst_label}"
            )

    # Hashtag advice
    if top_hashtags:
        top_tags_str = " ".join(f"#{t['hashtag']}" for t in top_hashtags[:3])
        recommendations.append(f"Your top hashtags are {top_tags_str} — use them more consistently")

    # Caption length advice
    active_buckets = {k: v for k, v in caption_length_performance.items() if v["post_count"] > 0}
    if active_buckets:
        best_bucket = max(active_buckets.items(), key=lambda x: x[1]["avg_engagement"])
        bucket_labels = {"short": "short (0-50 chars)", "medium": "medium (51-150 chars)",
                         "long": "long (151-300 chars)", "very_long": "very long (300+ chars)"}
        recommendations.append(
            f"{bucket_labels.get(best_bucket[0], best_bucket[0]).capitalize()} captions perform best — "
            f"avg engagement {best_bucket[1]['avg_engagement']:.2f}%"
        )

    # Engagement trend warning
    if len(engagement_trend) >= 2:
        recent = engagement_trend[-1]["avg_engagement"]
        older = engagement_trend[0]["avg_engagement"]
        if recent < older * 0.8:
            recommendations.append(
                f"Engagement is trending down: {older:.2f}% ({engagement_trend[0]['month']}) -> "
                f"{recent:.2f}% ({engagement_trend[-1]['month']}). Consider refreshing your content strategy."
            )

    # Posting frequency vs follower growth
    if follower_snapshots and len(follower_snapshots) >= 2 and follower_correlation:
        high_post_periods = [c for c in follower_correlation if c["posts_in_period"] > 0]
        if high_post_periods:
            growth_when_posting = [c["follower_change"] for c in high_post_periods if c["posts_in_period"] >= 2]
            growth_when_sparse = [c["follower_change"] for c in high_post_periods if c["posts_in_period"] < 2]
            if growth_when_posting and growth_when_sparse:
                avg_growth_active = statistics.mean(growth_when_posting)
                avg_growth_sparse = statistics.mean(growth_when_sparse)
                if avg_growth_active > avg_growth_sparse:
                    recommendations.append(
                        f"Posting more frequently correlates with better follower growth "
                        f"(avg +{avg_growth_active:.0f} vs +{avg_growth_sparse:.0f} followers per period)"
                    )

    return {
        "best_hours": best_hours,
        "best_day": best_day_result,
        "content_type_performance": content_type_performance,
        "hashtag_performance": {"top": top_hashtags, "bottom": bottom_hashtags},
        "caption_length_performance": caption_length_performance,
        "engagement_trend": engagement_trend,
        "recommendations": recommendations,
        "follower_correlation": follower_correlation,
    }


def analyze_content_studio(profile_data, posts_data):
    """Auto-categorize a profile, benchmark against niche averages, and generate
    content ideas, caption templates, hashtag recommendations, and performance insights."""

    # ── 1. Category keyword definitions ──────────────────────────────────────
    CATEGORY_KEYWORDS = {
        "beauty": ["makeup", "skincare", "beauty", "cosmetics", "lashes", "lipstick",
                    "foundation", "contour", "glow", "nails"],
        "fitness": ["fitness", "gym", "workout", "training", "gains", "bodybuilding",
                     "crossfit", "yoga", "pilates", "protein"],
        "food": ["food", "recipe", "cooking", "foodie", "chef", "baking",
                 "restaurant", "vegan", "healthy eating", "brunch"],
        "travel": ["travel", "wanderlust", "adventure", "explore", "backpacking",
                   "vacation", "destination", "beach", "hiking"],
        "fashion": ["fashion", "style", "outfit", "ootd", "streetwear", "designer",
                    "model", "clothing", "vintage", "trendy"],
        "tech": ["tech", "coding", "programming", "developer", "startup", "ai",
                 "software", "gadget", "innovation"],
        "art": ["art", "artist", "painting", "drawing", "illustration", "creative",
                "design", "sculpture", "photography"],
        "music": ["music", "musician", "singer", "guitar", "producer", "dj",
                  "band", "concert", "lyrics", "album"],
        "lifestyle": ["lifestyle", "daily", "motivation", "mindset", "self care",
                      "wellness", "home", "family"],
        "business": ["business", "entrepreneur", "ceo", "marketing", "brand",
                     "investment", "finance", "hustle", "leadership"],
        "gaming": ["gaming", "gamer", "twitch", "esports", "playstation", "xbox",
                   "streamer", "pc gaming"],
        "education": ["education", "learning", "teacher", "student", "study",
                      "tips", "tutorial", "howto"],
    }

    # ── 2. Category benchmarks (hardcoded realistic values) ──────────────────
    CATEGORY_BENCHMARKS = {
        "beauty": {
            "avg_engagement_rate": 3.5,
            "avg_followers": "10K–500K",
            "best_posting_frequency": 5,
            "best_content_type": "video",
            "peak_hours": [10, 13, 19],
            "top_hashtags": ["#beauty", "#makeup", "#skincare", "#glam", "#makeupartist",
                             "#beautytips", "#cosmetics", "#skincareroutine", "#glow", "#beautyblogger"],
        },
        "fitness": {
            "avg_engagement_rate": 3.2,
            "avg_followers": "5K–300K",
            "best_posting_frequency": 5,
            "best_content_type": "video",
            "peak_hours": [6, 12, 18],
            "top_hashtags": ["#fitness", "#gym", "#workout", "#fitfam", "#motivation",
                             "#bodybuilding", "#training", "#fitnessmotivation", "#gains", "#healthylifestyle"],
        },
        "food": {
            "avg_engagement_rate": 4.0,
            "avg_followers": "5K–250K",
            "best_posting_frequency": 7,
            "best_content_type": "carousel",
            "peak_hours": [11, 17, 20],
            "top_hashtags": ["#food", "#foodie", "#recipe", "#homemade", "#cooking",
                             "#foodporn", "#yummy", "#instafood", "#healthyfood", "#delicious"],
        },
        "travel": {
            "avg_engagement_rate": 4.5,
            "avg_followers": "10K–500K",
            "best_posting_frequency": 4,
            "best_content_type": "carousel",
            "peak_hours": [9, 14, 20],
            "top_hashtags": ["#travel", "#wanderlust", "#travelgram", "#explore", "#adventure",
                             "#travelphotography", "#instatravel", "#vacation", "#nature", "#traveltheworld"],
        },
        "fashion": {
            "avg_engagement_rate": 3.8,
            "avg_followers": "10K–1M",
            "best_posting_frequency": 5,
            "best_content_type": "carousel",
            "peak_hours": [10, 14, 19],
            "top_hashtags": ["#fashion", "#style", "#ootd", "#fashionblogger", "#streetstyle",
                             "#outfit", "#instafashion", "#trendy", "#fashionista", "#lookbook"],
        },
        "tech": {
            "avg_engagement_rate": 2.5,
            "avg_followers": "5K–200K",
            "best_posting_frequency": 4,
            "best_content_type": "carousel",
            "peak_hours": [9, 13, 17],
            "top_hashtags": ["#tech", "#technology", "#coding", "#programming", "#developer",
                             "#ai", "#startup", "#innovation", "#software", "#gadgets"],
        },
        "art": {
            "avg_engagement_rate": 4.2,
            "avg_followers": "5K–300K",
            "best_posting_frequency": 4,
            "best_content_type": "image",
            "peak_hours": [10, 15, 20],
            "top_hashtags": ["#art", "#artist", "#artwork", "#painting", "#drawing",
                             "#illustration", "#creative", "#design", "#digitalart", "#instaart"],
        },
        "music": {
            "avg_engagement_rate": 3.0,
            "avg_followers": "5K–500K",
            "best_posting_frequency": 4,
            "best_content_type": "video",
            "peak_hours": [12, 17, 21],
            "top_hashtags": ["#music", "#musician", "#newmusic", "#singer", "#guitar",
                             "#producer", "#hiphop", "#rap", "#livemusic", "#songwriter"],
        },
        "lifestyle": {
            "avg_engagement_rate": 3.3,
            "avg_followers": "5K–300K",
            "best_posting_frequency": 5,
            "best_content_type": "carousel",
            "peak_hours": [8, 12, 19],
            "top_hashtags": ["#lifestyle", "#motivation", "#dailylife", "#mindset", "#selfcare",
                             "#wellness", "#inspiration", "#positivity", "#lifestyleblogger", "#goals"],
        },
        "business": {
            "avg_engagement_rate": 2.8,
            "avg_followers": "5K–200K",
            "best_posting_frequency": 5,
            "best_content_type": "carousel",
            "peak_hours": [8, 12, 17],
            "top_hashtags": ["#business", "#entrepreneur", "#marketing", "#success", "#startup",
                             "#hustle", "#leadership", "#finance", "#branding", "#ceo"],
        },
        "gaming": {
            "avg_engagement_rate": 3.6,
            "avg_followers": "5K–500K",
            "best_posting_frequency": 6,
            "best_content_type": "video",
            "peak_hours": [15, 19, 22],
            "top_hashtags": ["#gaming", "#gamer", "#twitch", "#esports", "#playstation",
                             "#xbox", "#pcgaming", "#streamer", "#gamingcommunity", "#videogames"],
        },
        "education": {
            "avg_engagement_rate": 3.0,
            "avg_followers": "5K–200K",
            "best_posting_frequency": 5,
            "best_content_type": "carousel",
            "peak_hours": [8, 13, 18],
            "top_hashtags": ["#education", "#learning", "#study", "#teacher", "#student",
                             "#tips", "#tutorial", "#knowledge", "#edtech", "#studygram"],
        },
    }

    # ── 3. Content ideas per category ────────────────────────────────────────
    CONTENT_IDEAS = {
        "beauty": [
            "Before/after transformation reel",
            "Get ready with me (GRWM) morning routine",
            "Product review and swatch carousel",
            "Skincare routine breakdown with close-ups",
            "Trending makeup look tutorial",
        ],
        "fitness": [
            "Full workout routine reel with form tips",
            "Weekly meal prep and macro breakdown",
            "30-day challenge progress timelapse",
            "Exercise myth-busting carousel",
            "Day in the life of a fitness routine",
        ],
        "food": [
            "Meal prep timelapse",
            "Recipe step-by-step carousel",
            "Restaurant review reel with ratings",
            "What I eat in a day vlog-style reel",
            "Quick 60-second recipe tutorial",
        ],
        "travel": [
            "Hidden gems in [destination] carousel",
            "Travel packing tips and hacks reel",
            "Budget breakdown for a weekend trip",
            "Cinematic destination reveal reel",
            "Top 5 must-visit spots carousel",
        ],
        "fashion": [
            "Outfit of the week carousel",
            "Thrift haul try-on reel",
            "How to style one piece five ways",
            "Seasonal capsule wardrobe guide carousel",
            "Street style lookbook reel",
        ],
        "tech": [
            "Gadget unboxing and first impressions reel",
            "Coding tutorial for beginners carousel",
            "Tech setup / desk tour video",
            "App of the week review carousel",
            "Day in the life of a developer reel",
        ],
        "art": [
            "Painting process timelapse reel",
            "Art supply review and comparison carousel",
            "Sketch to finished piece transformation",
            "Creative challenge with fan-picked themes",
            "Behind the scenes of a commission",
        ],
        "music": [
            "Song cover or remix reel",
            "Studio session behind the scenes",
            "Gear breakdown and review carousel",
            "How I wrote this song — storytelling reel",
            "Live performance snippet with crowd reaction",
        ],
        "lifestyle": [
            "Morning routine reel",
            "Weekly habit tracker and reflection carousel",
            "Self-care Sunday vlog-style reel",
            "Room makeover or home tour",
            "Monthly goals and wins recap carousel",
        ],
        "business": [
            "Day in the life of an entrepreneur reel",
            "Top lessons learned this quarter carousel",
            "Revenue milestone breakdown (transparent numbers)",
            "Tool stack I use to run my business carousel",
            "Quick marketing tip reel under 30 seconds",
        ],
        "gaming": [
            "Epic gameplay highlight reel",
            "Game review and rating carousel",
            "Setup tour and gear recommendations",
            "Funny moments compilation reel",
            "Tips and tricks for beginners carousel",
        ],
        "education": [
            "Quick explainer reel on a tricky topic",
            "Study tips and techniques carousel",
            "Day in the life of a student / teacher reel",
            "Book recommendations carousel with mini-reviews",
            "Myth vs fact quiz-style reel",
        ],
    }

    # ── 4. Caption templates per category ────────────────────────────────────
    CAPTION_TEMPLATES = {
        "beauty": [
            "New look alert! Tried {product} and here's my honest take. Would you try it? Drop a {emoji} below!",
            "My {time_of_day} skincare routine in 3 steps. Step 1: {step}. What's your go-to product?",
            "Obsessed with this {trend} look! Tutorial coming soon — save this for later {emoji}",
        ],
        "fitness": [
            "Today's workout: {exercise}. {sets} sets x {reps} reps. Save this for your next gym day!",
            "{days}-day challenge update! Feeling {feeling}. Who's joining me? Comment {emoji} if you're in!",
            "Fuel your gains: {meal} packed with {macros}. Full recipe in highlights!",
        ],
        "food": [
            "Made {dish} from scratch and it only took {time} minutes! Recipe in carousel — swipe {emoji}",
            "Rating this {restaurant} spot: {rating}/10. The {dish} was {adjective}! Have you been?",
            "What I eat in a day: {meal_count} meals, all under {calories} cal. Save for inspo!",
        ],
        "travel": [
            "Exploring {destination}! This hidden gem blew my mind {emoji}. Adding to your bucket list?",
            "{days} days in {destination} for ${budget}. Full budget breakdown in the carousel!",
            "Sunsets in {destination} hit different {emoji}. Where should I go next? Drop suggestions!",
        ],
        "fashion": [
            "Today's fit: {item_1} + {item_2}. Styled {count} ways in the carousel — which is your fave?",
            "Thrift haul alert! Everything under ${price}. Swipe to see what I found {emoji}",
            "Building a capsule wardrobe for {season}. These {count} pieces are all you need!",
        ],
        "tech": [
            "Just unboxed the {gadget}! First impressions: {opinion}. Full review coming {emoji}",
            "{count} tools I use daily as a {role}. Number {number} is a game changer!",
            "Coded {project} in {time}. Here's how — step-by-step in the carousel {emoji}",
        ],
        "art": [
            "From blank canvas to {piece}: {hours} hours of work in {time} seconds {emoji}",
            "Trying {medium} for the first time! What do you think — keep going or stick to {usual_medium}?",
            "Commission piece for {client_type}: swipe to see the full process {emoji}",
        ],
        "music": [
            "Dropped a cover of {song}! Link in bio {emoji}. What should I cover next?",
            "Behind the scenes of {project}. The process is just as important as the product {emoji}",
            "New gear day! Got the {gear}. Sound test in the reel — thoughts?",
        ],
        "lifestyle": [
            "My {time_of_day} routine that changed everything. Step {number} is non-negotiable {emoji}",
            "Weekly reset: {count} habits I'm tracking this week. How do you stay on track?",
            "{season} self-care essentials: {item_1}, {item_2}, and {item_3}. What's on your list?",
        ],
        "business": [
            "Month {number} in business: {metric}. Here's what I'd do differently {emoji}",
            "{count} marketing strategies that actually work in {year}. Save this carousel!",
            "From {start} to {current}: my journey so far. Biggest lesson? {lesson} {emoji}",
        ],
        "gaming": [
            "This {game} moment was insane {emoji}! Have you tried it yet?",
            "My setup tour: {item_1}, {item_2}, {item_3}. Total cost? ${price}. Worth it!",
            "Top {count} tips for {game}. Number {number} will change your gameplay {emoji}",
        ],
        "education": [
            "Learn {topic} in {time} seconds! Save this for later {emoji}",
            "{count} study tips that got me through {subject}. Which one do you swear by?",
            "Myth: {myth}. Fact: {fact}. Swipe for {count} more {emoji}",
        ],
    }

    # ── Build searchable text corpus ─────────────────────────────────────────
    bio = (profile_data.get("biography") or "").lower()
    all_captions = []
    all_hashtags = []
    for post in (posts_data or []):
        caption = (post.get("caption") or "").lower()
        all_captions.append(caption)
        hashtags = post.get("hashtags") or []
        all_hashtags.extend([h.lower().strip("#") for h in hashtags])

    corpus = bio + " " + " ".join(all_captions) + " " + " ".join(all_hashtags)

    # ── Score categories ─────────────────────────────────────────────────────
    category_scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            score += len(re.findall(r'\b' + re.escape(kw) + r'\b', corpus))
        category_scores[cat] = score

    total_matches = sum(category_scores.values()) or 1
    scored = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)
    top3 = scored[:3]

    categories = [
        {"name": name, "score": score, "confidence": round(score / total_matches * 100, 1)}
        for name, score in top3 if score > 0
    ]

    # Fallback if nothing matched
    if not categories:
        categories = [{"name": "lifestyle", "score": 0, "confidence": 0.0}]

    primary_category = categories[0]["name"]

    # ── Benchmarks for detected categories ───────────────────────────────────
    benchmarks = {}
    for cat_info in categories:
        cname = cat_info["name"]
        benchmarks[cname] = CATEGORY_BENCHMARKS.get(cname, CATEGORY_BENCHMARKS["lifestyle"])

    # ── Content ideas for detected categories ────────────────────────────────
    content_ideas = {}
    for cat_info in categories:
        cname = cat_info["name"]
        content_ideas[cname] = CONTENT_IDEAS.get(cname, CONTENT_IDEAS["lifestyle"])

    # ── Caption templates for detected categories ────────────────────────────
    caption_templates = {}
    for cat_info in categories:
        cname = cat_info["name"]
        caption_templates[cname] = CAPTION_TEMPLATES.get(cname, CAPTION_TEMPLATES["lifestyle"])

    # ── 5. Performance comparison vs benchmark ───────────────────────────────
    followers = profile_data.get("followers") or 0
    total_posts = len(posts_data or [])

    # Compute user's actual engagement rate
    if posts_data and followers > 0:
        engagement_rates = []
        for post in posts_data:
            likes = post.get("likes") or 0
            comments = post.get("comments") or 0
            engagement_rates.append((likes + comments) / followers * 100)
        user_engagement_rate = statistics.mean(engagement_rates) if engagement_rates else 0.0
    else:
        user_engagement_rate = 0.0

    # Estimate posting frequency (posts per week)
    if len(posts_data or []) >= 2:
        dates = []
        for post in posts_data:
            ts = post.get("timestamp") or post.get("date")
            if ts:
                if isinstance(ts, (int, float)):
                    dates.append(datetime.fromtimestamp(ts))
                elif isinstance(ts, str):
                    try:
                        dates.append(datetime.fromisoformat(ts))
                    except ValueError:
                        pass
        if len(dates) >= 2:
            dates.sort()
            span_days = max((dates[-1] - dates[0]).days, 1)
            user_posting_freq = len(dates) / span_days * 7
        else:
            user_posting_freq = 0.0
    else:
        user_posting_freq = 0.0

    # Content mix: count types
    type_counter = Counter()
    for post in (posts_data or []):
        ptype = (post.get("type") or post.get("media_type") or "image").lower()
        type_counter[ptype] += 1
    user_dominant_type = type_counter.most_common(1)[0][0] if type_counter else "image"

    bench = CATEGORY_BENCHMARKS.get(primary_category, CATEGORY_BENCHMARKS["lifestyle"])

    def _compare(user_val, bench_val, tolerance=0.15):
        if user_val >= bench_val * (1 + tolerance):
            return "above_benchmark"
        elif user_val <= bench_val * (1 - tolerance):
            return "below_benchmark"
        return "at_benchmark"

    performance_comparison = {
        "engagement_rate": {
            "user": round(user_engagement_rate, 2),
            "benchmark": bench["avg_engagement_rate"],
            "status": _compare(user_engagement_rate, bench["avg_engagement_rate"]),
        },
        "posting_frequency": {
            "user": round(user_posting_freq, 1),
            "benchmark": bench["best_posting_frequency"],
            "status": _compare(user_posting_freq, bench["best_posting_frequency"]),
        },
        "content_type": {
            "user": user_dominant_type,
            "benchmark": bench["best_content_type"],
            "status": "at_benchmark" if user_dominant_type == bench["best_content_type"] else "below_benchmark",
        },
    }

    # ── 6. Trending / recommended hashtags ───────────────────────────────────
    # Best-performing user hashtags (by avg engagement of posts containing them)
    hashtag_engagement = defaultdict(list)
    for post in (posts_data or []):
        likes = post.get("likes") or 0
        comments = post.get("comments") or 0
        eng = likes + comments
        for h in (post.get("hashtags") or []):
            hashtag_engagement[h.lower().strip("#")].append(eng)

    user_top_hashtags = sorted(
        hashtag_engagement.keys(),
        key=lambda h: statistics.mean(hashtag_engagement[h]) if hashtag_engagement[h] else 0,
        reverse=True,
    )[:10]

    # Merge benchmark hashtags with user's best-performing ones
    niche_hashtags = [h.strip("#").lower() for h in bench.get("top_hashtags", [])]
    seen = set()
    recommended_hashtags = []
    for h in niche_hashtags + user_top_hashtags:
        if h not in seen:
            seen.add(h)
            recommended_hashtags.append(f"#{h}")
    recommended_hashtags = recommended_hashtags[:20]

    # ── Insights / recommendations ───────────────────────────────────────────
    insights = []
    er_status = performance_comparison["engagement_rate"]["status"]
    pf_status = performance_comparison["posting_frequency"]["status"]
    ct_status = performance_comparison["content_type"]["status"]

    if er_status == "below_benchmark":
        insights.append(
            f"Your engagement rate ({user_engagement_rate:.2f}%) is below the {primary_category} "
            f"average ({bench['avg_engagement_rate']}%). Try using more calls-to-action in captions "
            f"and posting during peak hours: {bench['peak_hours']}."
        )
    elif er_status == "above_benchmark":
        insights.append(
            f"Great job! Your engagement rate ({user_engagement_rate:.2f}%) exceeds the "
            f"{primary_category} niche average ({bench['avg_engagement_rate']}%). Keep it up!"
        )

    if pf_status == "below_benchmark":
        insights.append(
            f"You're posting ~{user_posting_freq:.1f} times/week. The recommended frequency for "
            f"{primary_category} is {bench['best_posting_frequency']} posts/week. Consider increasing output."
        )
    elif pf_status == "above_benchmark":
        insights.append(
            f"You're posting more frequently ({user_posting_freq:.1f}/week) than the typical "
            f"{primary_category} creator ({bench['best_posting_frequency']}/week). Watch for audience fatigue."
        )

    if ct_status == "below_benchmark":
        insights.append(
            f"Your most-used content type is '{user_dominant_type}', but '{bench['best_content_type']}' "
            f"tends to perform best in {primary_category}. Try mixing in more {bench['best_content_type']} content."
        )

    if not insights:
        insights.append(
            f"You're performing at or above benchmark across the board for {primary_category}. "
            f"Experiment with new content ideas to keep growing!"
        )

    return {
        "categories": categories,
        "primary_category": primary_category,
        "benchmarks": benchmarks,
        "content_ideas": content_ideas,
        "caption_templates": caption_templates,
        "performance_comparison": performance_comparison,
        "recommended_hashtags": recommended_hashtags,
        "insights": insights,
    }


def analyze_follower_demographics(followers_list):
    """Analyze follower demographics: name origins, country hints, regions, gender."""
    if not followers_list:
        return {
            "language_distribution": {},
            "country_hints": {},
            "region_distribution": {},
            "gender_distribution": {},
            "total_analyzed": 0,
            "detection_rate": 0.0,
        }

    # ── Name sets by language/culture ────────────────────────────────────────
    HEBREW_NAMES = {
        "yosef", "moshe", "david", "sarah", "rachel", "haim", "noa", "yael",
        "omer", "tal", "gal", "ori", "lior", "rotem", "shir", "amit", "ido",
        "nir", "ofir", "tamar", "maya", "michal", "alon", "eyal", "itay",
        "noam", "ariel", "chen", "liron", "mor", "shahar", "bar", "shai",
        "dor", "adi", "rom", "kfir", "raz", "zohar", "matan", "avraham",
        "rivka", "miriam", "esther", "malka", "shoshana", "elad", "tomer",
        "yonatan", "eliran", "sapir", "or", "maayan", "eden", "lia", "ella",
        "daniel", "ron", "uri", "nadav", "gilad", "assaf", "guy", "liad",
        "dean", "sean",
    }
    ARABIC_NAMES = {
        "ahmed", "mohammed", "ali", "fatima", "omar", "hassan", "aisha",
        "youssef", "khalid", "ibrahim", "mustafa", "layla", "amira", "samir",
        "nadia", "tariq", "zainab", "rania", "bilal", "kareem",
    }
    SPANISH_NAMES = {
        "carlos", "maria", "juan", "pedro", "diego", "lucia", "carmen",
        "pablo", "rosa", "luis", "jorge", "alejandra", "sofia", "santiago",
        "valentina", "miguel", "ana", "fernanda", "rafael", "isabella",
    }
    TURKISH_NAMES = {
        "mehmet", "ahmet", "mustafa", "elif", "ayse", "fatma", "emre",
        "burak", "deniz", "zeynep", "ece", "berk", "ceren", "can", "tugce",
        "serkan", "ozge", "mert", "selin", "umut",
    }
    RUSSIAN_NAMES = {
        "ivan", "sergei", "natasha", "olga", "dmitri", "anna", "pavel",
        "elena", "andrei", "tatiana", "nikita", "maria", "alexei", "yulia",
        "vladimir", "svetlana", "boris", "irina", "maxim", "katya",
    }
    FRENCH_NAMES = {
        "jean", "pierre", "marie", "claude", "sophie", "camille", "antoine",
        "juliette", "nicolas", "amelie", "louis", "charlotte", "hugo", "lea",
        "mathieu",
    }
    PORTUGUESE_NAMES = {
        "joao", "pedro", "lucas", "gabriel", "leticia", "larissa", "bruno",
        "thiago", "amanda", "jessica",
    }

    # ── Country code patterns in usernames ───────────────────────────────────
    COUNTRY_PATTERNS = {
        "Israel": ["_il", "_isr"],
        "Brazil": ["_br"],
        "Turkey": ["_tr"],
        "Indonesia": ["_id"],
        "India": ["_in"],
        "Mexico": ["_mx"],
        "Russia": ["_ru"],
        "Italy": ["_it"],
        "France": ["_fr"],
        "Germany": ["_de"],
        "Japan": ["_jp"],
        "Korea": ["_kr"],
        "Argentina": ["_ar"],
        "Spain": ["_es"],
        "UK": ["_uk", "_gb"],
        "USA": ["_us", "_usa"],
        "Philippines": ["_ph"],
        "Iran": ["_ir"],
        "Egypt": ["_eg"],
        "Saudi Arabia": ["_sa"],
        "UAE": ["_ae", "_uae"],
        "Colombia": ["_co"],
        "Chile": ["_cl"],
        "Poland": ["_pl"],
        "Netherlands": ["_nl"],
        "Australia": ["_au"],
        "Canada": ["_ca"],
    }

    # ── Region mapping ───────────────────────────────────────────────────────
    LANGUAGE_TO_REGION = {
        "Hebrew": "Middle East",
        "Arabic": "Middle East",
        "Turkish": "Middle East",
        "French": "Europe",
        "Russian/Slavic": "Europe",
        "English/Western": "Europe",
        "Spanish": "Latin America",
        "Portuguese/Brazilian": "Latin America",
        "Other Asian": "Asia Pacific",
    }
    COUNTRY_TO_REGION = {
        "Israel": "Middle East",
        "Iran": "Middle East",
        "Egypt": "Middle East",
        "Saudi Arabia": "Middle East",
        "UAE": "Middle East",
        "Turkey": "Middle East",
        "UK": "Europe",
        "France": "Europe",
        "Germany": "Europe",
        "Italy": "Europe",
        "Spain": "Europe",
        "Russia": "Europe",
        "Poland": "Europe",
        "Netherlands": "Europe",
        "Brazil": "Latin America",
        "Argentina": "Latin America",
        "Mexico": "Latin America",
        "Colombia": "Latin America",
        "Chile": "Latin America",
        "USA": "North America",
        "Canada": "North America",
        "Japan": "Asia Pacific",
        "Korea": "Asia Pacific",
        "India": "Asia Pacific",
        "Indonesia": "Asia Pacific",
        "Philippines": "Asia Pacific",
        "Australia": "Asia Pacific",
    }

    total = len(followers_list)
    language_counter = Counter()
    country_counter = Counter()
    region_counter = Counter()
    gender_counter = Counter()
    detected_count = 0

    for follower in followers_list:
        full_name = follower.get("full_name", "") or ""
        username = follower.get("username", "") or ""
        name_lower = full_name.lower().strip()
        username_lower = username.lower().strip()

        detected = False

        # ── 1. Language/culture detection from full_name ─────────────────
        name_parts = re.split(r"[\s\-_]+", name_lower)
        name_parts = [p for p in name_parts if p]

        matched_language = None
        best_score = 0

        # Check each language set
        lang_sets = [
            ("Hebrew", HEBREW_NAMES),
            ("Arabic", ARABIC_NAMES),
            ("Spanish", SPANISH_NAMES),
            ("Turkish", TURKISH_NAMES),
            ("Russian/Slavic", RUSSIAN_NAMES),
            ("English/Western", FEMALE_NAMES | MALE_NAMES),
            ("French", FRENCH_NAMES),
            ("Portuguese/Brazilian", PORTUGUESE_NAMES),
        ]

        for lang, name_set in lang_sets:
            score = sum(1 for part in name_parts if part in name_set)
            if score > best_score:
                best_score = score
                matched_language = lang

        # Hebrew suffix heuristics: names ending in -el, -it, -ya
        if best_score == 0 and name_parts:
            for part in name_parts:
                if len(part) >= 3 and (
                    part.endswith("el") or part.endswith("it") or part.endswith("ya")
                ):
                    matched_language = "Hebrew"
                    best_score = 1
                    break

        # Portuguese/Brazilian heuristic: names ending in -ão, -inho
        if best_score == 0 and name_parts:
            for part in name_parts:
                if part.endswith("ão") or part.endswith("inho"):
                    matched_language = "Portuguese/Brazilian"
                    best_score = 1
                    break

        # Other Asian heuristic: very short names (1-2 chars per part)
        if best_score == 0 and name_parts:
            short_parts = [p for p in name_parts if 1 <= len(p) <= 2]
            if len(short_parts) >= 2 and len(short_parts) == len(name_parts):
                matched_language = "Other Asian"
                best_score = 1

        if matched_language:
            language_counter[matched_language] += 1
            detected = True

        # ── 2. Country detection from username ───────────────────────────
        matched_country = None
        for country, patterns in COUNTRY_PATTERNS.items():
            for pattern in patterns:
                if username_lower.endswith(pattern) or pattern in username_lower:
                    matched_country = country
                    break
            if matched_country:
                break

        if matched_country:
            country_counter[matched_country] += 1
            detected = True

        # ── 3. Region assignment ─────────────────────────────────────────
        region = None
        if matched_country and matched_country in COUNTRY_TO_REGION:
            region = COUNTRY_TO_REGION[matched_country]
        elif matched_language and matched_language in LANGUAGE_TO_REGION:
            region = LANGUAGE_TO_REGION[matched_language]

        if region:
            region_counter[region] += 1
        else:
            region_counter["Other/Unknown"] += 1

        # ── 4. Gender detection ──────────────────────────────────────────
        gender = guess_gender(full_name)
        gender_counter[gender] += 1

        if detected:
            detected_count += 1

    # ── Build result dicts with percentages ──────────────────────────────────
    def _dist(counter):
        return {
            key: {"count": count, "percentage": round(count / total * 100, 1)}
            for key, count in counter.most_common()
        }

    return {
        "language_distribution": _dist(language_counter),
        "country_hints": dict(country_counter.most_common()),
        "region_distribution": _dist(region_counter),
        "gender_distribution": _dist(gender_counter),
        "total_analyzed": total,
        "detection_rate": round(detected_count / total * 100, 1),
    }


def analyze_unfollowers(unfollowers_list):
    """Analyze unfollowers by gender, account type, and patterns."""
    if not unfollowers_list:
        return {
            "total": 0,
            "gender_breakdown": {},
            "private_accounts": 0,
            "verified_accounts": 0,
            "no_name_accounts": 0,
            "profiles": [],
        }

    genders = Counter()
    private_count = 0
    verified_count = 0
    no_name_count = 0
    profiles = []

    for u in unfollowers_list:
        full_name = u.get("full_name", "")
        g = guess_gender(full_name)
        if g == "likely_female":
            genders["female"] += 0.7
            genders["unknown"] += 0.3
        else:
            genders[g] += 1

        if u.get("is_private"):
            private_count += 1
        if u.get("is_verified"):
            verified_count += 1
        if not full_name:
            no_name_count += 1

        profiles.append({
            "username": u.get("username", ""),
            "full_name": full_name,
            "gender": g if g != "likely_female" else "female",
            "is_private": u.get("is_private", False),
            "is_verified": u.get("is_verified", False),
        })

    total = len(unfollowers_list)
    gender_breakdown = {}
    for g in ["female", "male", "unknown"]:
        count = genders.get(g, 0)
        gender_breakdown[g] = {
            "count": round(count),
            "percentage": round((count / total) * 100, 1) if total > 0 else 0,
        }

    # Account type analysis
    private_pct = round((private_count / total) * 100, 1) if total > 0 else 0
    no_name_pct = round((no_name_count / total) * 100, 1) if total > 0 else 0

    insights = []
    if no_name_pct > 50:
        insights.append(f"{no_name_pct}% of unfollowers had no display name — likely bot/spam accounts that were purged")
    if private_pct > 70:
        insights.append(f"{private_pct}% of unfollowers were private accounts")
    if verified_count > 0:
        insights.append(f"{verified_count} verified account(s) unfollowed you")

    return {
        "total": total,
        "gender_breakdown": gender_breakdown,
        "private_accounts": private_count,
        "private_percentage": private_pct,
        "verified_accounts": verified_count,
        "no_name_accounts": no_name_count,
        "no_name_percentage": no_name_pct,
        "insights": insights,
        "profiles": profiles,
    }


def analyze_lurkers(followers_list, engagement_map, story_viewer_history=None):
    """
    Cross-reference followers with engagement data to detect:
    - Ghost followers: follow but never engage
    - Secret fans: don't follow but consistently engage (like/comment/view stories)
    - Top engagers: most active followers
    - Story stalkers: non-followers who view stories
    - At-risk followers: used to engage but stopped (likely to unfollow)
    """
    follower_usernames = {f["username"] for f in followers_list}
    follower_map = {f["username"]: f for f in followers_list}

    # Build engagement frequency per user
    engagement_counts = Counter()  # username -> total interactions
    like_counts = Counter()
    comment_counts = Counter()
    engaged_posts = defaultdict(set)  # username -> set of post shortcodes

    all_engagers = {}  # username -> profile info

    for shortcode, post_data in engagement_map.items():
        for liker in post_data.get("likers", []):
            u = liker["username"]
            engagement_counts[u] += 1
            like_counts[u] += 1
            engaged_posts[u].add(shortcode)
            if u not in all_engagers:
                all_engagers[u] = liker

        for commenter in post_data.get("commenters", []):
            u = commenter["username"]
            engagement_counts[u] += 2  # comments weighted higher
            comment_counts[u] += 1
            engaged_posts[u].add(shortcode)
            if u not in all_engagers:
                all_engagers[u] = commenter

    engaged_usernames = set(engagement_counts.keys())
    total_posts = len(engagement_map)

    # ── Ghost followers: follow but never liked/commented ──
    ghost_usernames = follower_usernames - engaged_usernames
    ghost_followers = []
    for u in sorted(ghost_usernames):
        info = follower_map.get(u, {})
        g = guess_gender(info.get("full_name", ""))
        ghost_followers.append({
            "username": u,
            "full_name": info.get("full_name", ""),
            "gender": g if g != "likely_female" else "female",
            "is_private": info.get("is_private", False),
            "is_verified": info.get("is_verified", False),
        })

    # ── Secret fans: engage but don't follow ──
    secret_fan_usernames = engaged_usernames - follower_usernames
    secret_fans = []
    for u in secret_fan_usernames:
        info = all_engagers.get(u, {})
        g = guess_gender(info.get("full_name", ""))
        secret_fans.append({
            "username": u,
            "full_name": info.get("full_name", ""),
            "gender": g if g != "likely_female" else "female",
            "is_private": info.get("is_private", False),
            "is_verified": info.get("is_verified", False),
            "total_interactions": engagement_counts[u],
            "likes": like_counts[u],
            "comments": comment_counts[u],
            "posts_engaged": len(engaged_posts[u]),
        })
    secret_fans.sort(key=lambda x: x["total_interactions"], reverse=True)

    # ── Top engagers (followers who engage most) ──
    top_engagers = []
    for u in (follower_usernames & engaged_usernames):
        info = follower_map.get(u, all_engagers.get(u, {}))
        g = guess_gender(info.get("full_name", ""))
        engagement_rate = (len(engaged_posts[u]) / total_posts * 100) if total_posts > 0 else 0
        top_engagers.append({
            "username": u,
            "full_name": info.get("full_name", ""),
            "gender": g if g != "likely_female" else "female",
            "total_interactions": engagement_counts[u],
            "likes": like_counts[u],
            "comments": comment_counts[u],
            "posts_engaged": len(engaged_posts[u]),
            "engagement_rate": round(engagement_rate, 1),
        })
    top_engagers.sort(key=lambda x: x["total_interactions"], reverse=True)

    # ── Story stalkers: non-followers who view stories ──
    story_stalkers = []
    all_story_viewers = Counter()
    if story_viewer_history:
        for snapshot in story_viewer_history:
            for story in snapshot.get("stories", []):
                for viewer in story.get("viewers", []):
                    all_story_viewers[viewer["username"]] += 1

        stalker_usernames = set(all_story_viewers.keys()) - follower_usernames
        for u in stalker_usernames:
            # Try to get profile info from engagement data or story data
            info = all_engagers.get(u, {})
            if not info:
                # Search story viewer data for profile info
                for snapshot in story_viewer_history:
                    for story in snapshot.get("stories", []):
                        for viewer in story.get("viewers", []):
                            if viewer["username"] == u:
                                info = viewer
                                break
                        if info:
                            break
                    if info:
                        break

            g = guess_gender(info.get("full_name", ""))
            story_stalkers.append({
                "username": u,
                "full_name": info.get("full_name", ""),
                "gender": g if g != "likely_female" else "female",
                "is_private": info.get("is_private", False),
                "stories_viewed": all_story_viewers[u],
                "also_engages": u in engaged_usernames,
            })
        story_stalkers.sort(key=lambda x: x["stories_viewed"], reverse=True)

    # ── Gender analysis across categories ──
    def gender_stats(profiles):
        genders = Counter()
        for p in profiles:
            genders[p.get("gender", "unknown")] += 1
        total = len(profiles)
        return {
            g: {"count": c, "percentage": round(c / total * 100, 1) if total > 0 else 0}
            for g, c in [("female", genders.get("female", 0)),
                         ("male", genders.get("male", 0)),
                         ("unknown", genders.get("unknown", 0))]
        }

    # ── Insights ──
    insights = []
    ghost_pct = round(len(ghost_followers) / len(followers_list) * 100, 1) if followers_list else 0
    if ghost_pct > 50:
        insights.append(f"{ghost_pct}% of your followers are ghosts (never engage) — consider cleaning your follower list")
    elif ghost_pct > 30:
        insights.append(f"{ghost_pct}% of your followers are ghosts — this is normal for most accounts")

    if secret_fans:
        insights.append(f"You have {len(secret_fans)} secret fan(s) who engage but don't follow you")
    if story_stalkers:
        insights.append(f"{len(story_stalkers)} non-follower(s) view your stories regularly")
    if top_engagers:
        top3 = ", ".join(f"@{e['username']}" for e in top_engagers[:3])
        insights.append(f"Your most loyal fans: {top3}")

    return {
        "summary": {
            "total_followers": len(followers_list),
            "total_posts_analyzed": total_posts,
            "ghost_followers_count": len(ghost_followers),
            "ghost_followers_percentage": ghost_pct,
            "secret_fans_count": len(secret_fans),
            "top_engagers_count": len(top_engagers),
            "story_stalkers_count": len(story_stalkers),
            "total_story_scans": len(story_viewer_history) if story_viewer_history else 0,
        },
        "ghost_followers": ghost_followers,
        "ghost_gender": gender_stats(ghost_followers),
        "secret_fans": secret_fans,
        "secret_fans_gender": gender_stats(secret_fans) if secret_fans else {},
        "top_engagers": top_engagers[:50],
        "top_engagers_gender": gender_stats(top_engagers[:50]) if top_engagers else {},
        "story_stalkers": story_stalkers,
        "story_stalkers_gender": gender_stats(story_stalkers) if story_stalkers else {},
        "insights": insights,
    }


def save_json(data, filepath):
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()
