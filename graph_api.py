"""
Instagram Graph API publishing and Facebook OAuth helpers.

Provides functions for Facebook OAuth flow, Instagram Business Account
discovery, token management, and content publishing (photos, carousels, reels).
"""

import time
from urllib.parse import urlencode

import requests

BASE_URL = "https://graph.facebook.com/v21.0/"

OAUTH_SCOPES = [
    "pages_manage_posts",
    "pages_read_engagement",
    "pages_show_list",
]


class GraphAPIError(Exception):
    """Raised when an Instagram Graph API or Facebook API call fails."""
    pass


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------

def get_facebook_auth_url(app_id, redirect_uri, state):
    """Return the Facebook OAuth dialog URL for requesting permissions.

    Args:
        app_id: Facebook App ID.
        redirect_uri: URL Facebook will redirect back to after auth.
        state: An opaque CSRF-protection string.

    Returns:
        The full authorization URL as a string.
    """
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": ",".join(OAUTH_SCOPES),
        "response_type": "code",
    }
    return f"https://www.facebook.com/v21.0/dialog/oauth?{urlencode(params)}"


def exchange_code_for_token(code, app_id, app_secret, redirect_uri):
    """Exchange an OAuth authorization code for a long-lived access token.

    First exchanges the code for a short-lived token, then exchanges that
    for a long-lived token (valid ~60 days).

    Args:
        code: The authorization code from the OAuth redirect.
        app_id: Facebook App ID.
        app_secret: Facebook App Secret.
        redirect_uri: Must match the redirect_uri used in the auth request.

    Returns:
        dict with keys ``access_token`` and ``expires_in``.

    Raises:
        GraphAPIError: If either token exchange request fails.
    """
    # Step 1: short-lived token
    resp = requests.get(
        f"{BASE_URL}oauth/access_token",
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to exchange code for short-lived token: "
            f"{data['error'].get('message', data['error'])}"
        )
    short_lived_token = data["access_token"]

    # Step 2: long-lived token
    resp = requests.get(
        f"{BASE_URL}oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_lived_token,
        },
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to exchange for long-lived token: "
            f"{data['error'].get('message', data['error'])}"
        )

    return {
        "access_token": data["access_token"],
        "expires_in": data.get("expires_in"),
    }


# ---------------------------------------------------------------------------
# Account discovery
# ---------------------------------------------------------------------------

def get_instagram_business_account(access_token):
    """Find the Instagram Business Account connected to the user's FB pages.

    Iterates over all Facebook Pages the user manages and returns the first
    one that has a connected Instagram Business Account.

    Args:
        access_token: A valid user access token with pages_read_engagement scope.

    Returns:
        dict with ``ig_user_id``, ``ig_username``, ``fb_page_id``,
        ``fb_page_name`` — or ``None`` if no connected account is found.

    Raises:
        GraphAPIError: If the API calls fail.
    """
    # List all pages the user manages
    resp = requests.get(
        f"{BASE_URL}me/accounts",
        params={"access_token": access_token},
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to list Facebook pages: "
            f"{data['error'].get('message', data['error'])}"
        )

    pages = data.get("data", [])
    print(f"[FB OAuth] Found {len(pages)} pages: {[p.get('name', p['id']) for p in pages]}")
    for page in pages:
        page_id = page["id"]
        # Use page access token if available (required for some permissions)
        page_token = page.get("access_token", access_token)
        resp2 = requests.get(
            f"{BASE_URL}{page_id}",
            params={
                "fields": "instagram_business_account,name",
                "access_token": page_token,
            },
        )
        page_data = resp2.json()
        print(f"[FB OAuth] Page {page.get('name', page_id)}: {page_data}")
        if "error" in page_data:
            continue

        ig_account = page_data.get("instagram_business_account")
        if ig_account:
            # Fetch the IG username
            ig_user_id = ig_account["id"]
            resp3 = requests.get(
                f"{BASE_URL}{ig_user_id}",
                params={
                    "fields": "username",
                    "access_token": access_token,
                },
            )
            ig_data = resp3.json()
            return {
                "ig_user_id": ig_user_id,
                "ig_username": ig_data.get("username"),
                "fb_page_id": page_id,
                "fb_page_name": page_data.get("name"),
            }

    return None


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

def refresh_token_if_needed(graph_account, app_id, app_secret):
    """Refresh the access token if it expires within 7 days.

    Updates ``graph_account.access_token`` and ``graph_account.token_expires_at``
    in-place but does **not** commit to the database.

    Args:
        graph_account: An InstagramGraphAccount model instance with attributes
            ``access_token``, ``token_expires_at``.
        app_id: Facebook App ID.
        app_secret: Facebook App Secret.

    Returns:
        True if the token was refreshed, False otherwise.

    Raises:
        GraphAPIError: If the refresh API call fails.
    """
    from datetime import datetime, timedelta

    if graph_account.token_expires_at is None:
        return False

    now = datetime.utcnow()
    if graph_account.token_expires_at - now > timedelta(days=7):
        return False

    resp = requests.get(
        f"{BASE_URL}oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": graph_account.access_token,
        },
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to refresh token: "
            f"{data['error'].get('message', data['error'])}"
        )

    graph_account.access_token = data["access_token"]
    expires_in = data.get("expires_in")
    if expires_in:
        graph_account.token_expires_at = now + timedelta(seconds=expires_in)

    return True


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

def publish_photo(access_token, ig_user_id, image_url, caption):
    """Publish a single photo to Instagram.

    Args:
        access_token: Valid access token with instagram_content_publish scope.
        ig_user_id: Instagram Business Account ID.
        image_url: Public URL of the image to publish.
        caption: Post caption text.

    Returns:
        dict with ``id`` (the published media ID).

    Raises:
        GraphAPIError: If container creation or publishing fails.
    """
    # Step 1: create media container
    resp = requests.post(
        f"{BASE_URL}{ig_user_id}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token,
        },
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to create photo container: "
            f"{data['error'].get('message', data['error'])}"
        )
    creation_id = data["id"]

    # Step 2: publish
    resp = requests.post(
        f"{BASE_URL}{ig_user_id}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": access_token,
        },
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to publish photo: "
            f"{data['error'].get('message', data['error'])}"
        )

    return {"id": data["id"]}


def publish_carousel(access_token, ig_user_id, image_urls, caption):
    """Publish a carousel (multi-image) post to Instagram.

    Args:
        access_token: Valid access token with instagram_content_publish scope.
        ig_user_id: Instagram Business Account ID.
        image_urls: List of public image URLs (2-10 images).
        caption: Post caption text.

    Returns:
        dict with ``id`` (the published media ID).

    Raises:
        GraphAPIError: If any container creation or publishing step fails.
    """
    # Step 1: create child containers
    children_ids = []
    for url in image_urls:
        resp = requests.post(
            f"{BASE_URL}{ig_user_id}/media",
            data={
                "image_url": url,
                "is_carousel_item": "true",
                "access_token": access_token,
            },
        )
        data = resp.json()
        if "error" in data:
            raise GraphAPIError(
                f"Failed to create carousel child container: "
                f"{data['error'].get('message', data['error'])}"
            )
        children_ids.append(data["id"])

    # Step 2: create carousel container
    resp = requests.post(
        f"{BASE_URL}{ig_user_id}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(children_ids),
            "caption": caption,
            "access_token": access_token,
        },
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to create carousel container: "
            f"{data['error'].get('message', data['error'])}"
        )
    creation_id = data["id"]

    # Step 3: publish
    resp = requests.post(
        f"{BASE_URL}{ig_user_id}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": access_token,
        },
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to publish carousel: "
            f"{data['error'].get('message', data['error'])}"
        )

    return {"id": data["id"]}


def check_container_status(access_token, container_id):
    """Check the processing status of a media container.

    Args:
        access_token: Valid access token.
        container_id: The container ID to check.

    Returns:
        Status code string: ``IN_PROGRESS``, ``FINISHED``, or ``ERROR``.

    Raises:
        GraphAPIError: If the status check API call fails.
    """
    resp = requests.get(
        f"{BASE_URL}{container_id}",
        params={
            "fields": "status_code,status",
            "access_token": access_token,
        },
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to check container status: "
            f"{data['error'].get('message', data['error'])}"
        )

    return data.get("status_code", "UNKNOWN")


def publish_reel(access_token, ig_user_id, video_url, caption, cover_url=None):
    """Publish a Reel (short video) to Instagram.

    Creates a REELS media container, polls until processing is complete,
    then publishes.

    Args:
        access_token: Valid access token with instagram_content_publish scope.
        ig_user_id: Instagram Business Account ID.
        video_url: Public URL of the video file.
        caption: Post caption text.
        cover_url: Optional public URL of the cover image.

    Returns:
        dict with ``id`` (the published media ID).

    Raises:
        GraphAPIError: If container creation, polling, or publishing fails.
    """
    # Step 1: create reel container
    payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": access_token,
    }
    if cover_url:
        payload["cover_url"] = cover_url

    resp = requests.post(
        f"{BASE_URL}{ig_user_id}/media",
        data=payload,
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to create reel container: "
            f"{data['error'].get('message', data['error'])}"
        )
    creation_id = data["id"]

    # Step 2: poll until processing finishes
    max_attempts = 60
    for attempt in range(max_attempts):
        status = check_container_status(access_token, creation_id)
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise GraphAPIError(
                f"Reel container {creation_id} processing failed with ERROR status."
            )
        time.sleep(3)
    else:
        raise GraphAPIError(
            f"Reel container {creation_id} did not finish processing after "
            f"{max_attempts * 3} seconds."
        )

    # Step 3: publish
    resp = requests.post(
        f"{BASE_URL}{ig_user_id}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": access_token,
        },
    )
    data = resp.json()
    if "error" in data:
        raise GraphAPIError(
            f"Failed to publish reel: "
            f"{data['error'].get('message', data['error'])}"
        )

    return {"id": data["id"]}
