import requests
import time
from collections import Counter
import pandas as pd

API_TOKEN = "c669a891-a2cf-4bf9-8656-49ab4eaeea33"

DISCOVER_URL_DATASET_ID = "gd_lu702nij2f790tmv9h"  # TikTok Discover by Discover URL
KEYWORD_DATASET_ID = "gd_KEYWORD_DATASET_ID"            # TikTok Discover by Keywords

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

TRIGGER_URL = "https://api.brightdata.com/datasets/v3/trigger"
SNAPSHOT_URL = "https://api.brightdata.com/datasets/v3/snapshot"


def trigger_scraper(dataset_id, inputs):
    """
    Trigger a Web Scraper API run.
    `inputs` is a list of input objects matching the scraper schema.
    Returns snapshot_id.
    """
    resp = requests.post(
        f"{TRIGGER_URL}?dataset_id={dataset_id}",
        headers=HEADERS,
        json=inputs
    )
    resp.raise_for_status()
    data = resp.json()
    return data["snapshot_id"]


def wait_for_snapshot(snapshot_id, poll_interval=5):
    """
    Poll snapshot until it's ready, then return the full JSON data.
    """
    start_time = time.time()
    attempt = 0
    spinner = ["|", "/", "-", "\\"]
    while True:
        attempt += 1
        resp = requests.get(f"{SNAPSHOT_URL}/{snapshot_id}?format=json", headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status")
        progress = (
            data.get("progress")
            or data.get("progress_pct")
            or data.get("progress_percent")
        )
        elapsed = int(time.time() - start_time)
        spin = spinner[attempt % len(spinner)]
        if progress is not None:
            print(
                f"\r[{spin}] Snapshot {snapshot_id} status={status} progress={progress}% elapsed={elapsed}s",
                end="",
                flush=True,
            )
        else:
            print(
                f"\r[{spin}] Snapshot {snapshot_id} status={status} elapsed={elapsed}s",
                end="",
                flush=True,
            )
        if status == "ready":
            print()
            # Some implementations return data directly under "data"
            if "data" in data:
                return data["data"]
            # Or the endpoint already returns the array
            return data

        if status == "failed":
            print()
            raise RuntimeError(f"Snapshot {snapshot_id} failed: {data}")

        time.sleep(poll_interval)


def collect_trending_from_discover(discover_urls, max_posts=None):
    """
    Step 1: Use Discover by Discover URL to get trending posts.
    `discover_urls` is a list of TikTok discover URLs.
    Returns a list of post records (dicts).
    """
    # Each input object must match the TikTok Discover-by-URL scraper schema.
    # Typically: {"url": "<discover_url>"}
    inputs = [{"url": u} for u in discover_urls]

    snapshot_id = trigger_scraper(DISCOVER_URL_DATASET_ID, inputs)
    data = wait_for_snapshot(snapshot_id)

    # Flatten if multiple inputs
    if isinstance(data, dict) and "results" in data:
        records = data["results"]
    else:
        records = data

    if max_posts:
        records = records[:max_posts]

    return records


def extract_top_hashtags(posts, top_n=20, min_length=2):
    """
    Step 2: From posts, extract hashtags and return top N by frequency.
    Assumes each post has a 'hashtags' field (list of strings or similar).
    """
    counter = Counter()

    for p in posts:
        hashtags = p.get("hashtags") or []
        # hashtags might be list of dicts or strings depending on template;
        # adjust this mapping as needed once you see real output.
        normalized = []
        for h in hashtags:
            if isinstance(h, dict):
                # e.g. {"name": "booktok"}
                name = h.get("name")
            else:
                name = str(h).lstrip("#")
            if name and len(name) >= min_length:
                normalized.append(name.lower())

        counter.update(normalized)

    top = [f"#{tag}" for tag, _ in counter.most_common(top_n)]
    return top


def collect_posts_by_keywords(hashtags, num_posts_per_hashtag=5):
    """
    Step 3: For each hashtag, use Discover by Keywords to get posts.
    Returns a combined list of posts.
    """
    inputs = []
    for tag in hashtags:
        inputs.append({
            # Adjust keys to match the TikTok keyword scraper schema.
            # Common pattern: {"search_keyword": tag, "num_of_posts": num_posts_per_hashtag}
            "search_keyword": tag,
            "num_of_posts": num_posts_per_hashtag
        })

    snapshot_id = trigger_scraper(KEYWORD_DATASET_ID, inputs)
    data = wait_for_snapshot(snapshot_id)

    if isinstance(data, dict) and "results" in data:
        records = data["results"]
    else:
        records = data

    return records


def rank_posts(posts, top_n=20):
    """
    Step 4: Rank posts by likes, views, comments.
    Uses a simple scoring formula; adjust as needed.
    Assumes fields: digg_count (likes), play_count (views), comment_count.
    """
    df = pd.DataFrame(posts)

    # Ensure numeric
    for col in ["digg_count", "play_count", "comment_count"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0

    # Optional: filter by recency if 'create_time' is available
    # Example: keep only last X days (engineer can add this later)

    # Normalize metrics to [0,1] to combine them
    def normalize(series):
        max_val = series.max()
        if max_val == 0:
            return series * 0
        return series / max_val

    df["likes_norm"] = normalize(df["digg_count"])
    df["views_norm"] = normalize(df["play_count"])
    df["comments_norm"] = normalize(df["comment_count"])

    # Simple weighted score – tweak weights as needed
    df["score"] = (
        0.5 * df["likes_norm"] +
        0.3 * df["views_norm"] +
        0.2 * df["comments_norm"]
    )

    df_sorted = df.sort_values("score", ascending=False)
    top_df = df_sorted.head(top_n)

    # Convert back to list of dicts
    return top_df.to_dict(orient="records")


def main():
    # 1) Seed: TikTok discover URLs (engineer should plug real URLs here)
    discover_urls = [
        "https://www.tiktok.com/discover",
        # Add category-specific discover URLs if needed
    ]

    # Step 1: Get trending posts from discover
    discover_posts = collect_trending_from_discover(
        discover_urls,
        max_posts=5  # cap for cost control
    )
    print(f"Collected {len(discover_posts)} posts from discover URLs")

    # # Step 2: Extract top hashtags
    # top_hashtags = extract_top_hashtags(discover_posts, top_n=20)
    # print("Top hashtags:", top_hashtags)

    # # Step 3: For each hashtag, get posts via Discover by Keywords
    # keyword_posts = collect_posts_by_keywords(
    #     top_hashtags,
    #     num_posts_per_hashtag=5  # cost control
    # )
    # print(f"Collected {len(keyword_posts)} posts from keyword search")

    # # Step 4: Rank posts and take top 10–20
    # top_posts = rank_posts(keyword_posts, top_n=20)
    # print("Top posts (for analysis):")
    # for i, p in enumerate(top_posts, start=1):
    #     print(
    #         f"{i}. URL: {p.get('url')}, "
    #         f"likes={p.get('digg_count')}, "
    #         f"views={p.get('play_count')}, "
    #         f"comments={p.get('comment_count')}, "
    #         f"score={round(p.get('score', 0), 3)}"
    #     )

    # # At this point, `top_posts` is your MVP output:
    # # - pass to another agent/model for creative analysis
    # # - store in DB
    # # - run NLP on descriptions/comments, etc.


if __name__ == "__main__":
    main()
