import asyncio
import json
import os
import time
from typing import Optional

import tweepy
import tweepy.errors
import twscrape
from twscrape import API as TwscrapeAPI, gather
from dotenv import load_dotenv

from services.social.platform_adapter import PlatformAdapter, Post, PostResult

load_dotenv()

WATCHED_TOPICS = [
    "AI alignment",
    "LLM agents",
    "machine learning production",
    "software architecture",
    "tech industry layoffs",
    "AGI",
]

MIN_LIKES     = 10
MIN_RETWEETS  = 2
SEARCH_LIMIT  = 15 

def _parse_cookie_string(cookie_str: str) -> dict:
    from urllib.parse import unquote

    # Only these matter to twscrape — everything else is tracking noise
    WANTED = {"auth_token", "ct0", "twid", "lang"}

    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name  = name.strip()
        value = value.strip()

        if name not in WANTED:
            continue

        # Decode URL-encoding (v1%3A... → v1:...)
        value = unquote(value)
        # Strip wrapping quotes ("value" → value)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]

        cookies[name] = value
    print(f"✅ Parsed {len(cookies)} relevant cookies: {list(cookies.keys())}")
    
    if "ct0" in cookies:
        print(f"   ct0 length: {len(cookies['ct0'])} (Should be approx 160)")
        if len(cookies["ct0"]) < 100:
            print("   ⚠️ WARNING: ct0 looks suspiciously short! Did you copy a truncated value?")
    
    if "auth_token" not in cookies:
        print(
            "[X] WARNING: 'auth_token' not found in X_COOKIES.\n"
            "    This is the required session cookie — without it twscrape cannot log in.\n"
            "    How to get it:\n"
            "      1. Open x.com in your browser and log in\n"
            "      2. DevTools (F12) → Application → Cookies → https://x.com\n"
            "      3. Find 'auth_token' and copy its value\n"
            "      4. Add it to your cookie string in X_COOKIES"
        )
    if "ct0" not in cookies:
        print("[X] WARNING: 'ct0' not found in X_COOKIES. This CSRF token is also required.")

    return cookies

class XAdapter(PlatformAdapter):
    def __init__(self):
        self._tweepy: Optional[tweepy.Client] = None
        self._scraper: Optional[TwscrapeAPI] = None

        self._last_post_time: float = 0.0
        self._own_username: str = os.getenv("X_SCRAPE_USERNAME", "")
        
    @property
    def platform_name(self) -> str:
        return "x"
    
    def rate_limit_config(self) -> dict:
        return {
            "max_posts_per_hour":   1,    
            "min_seconds_between":  1800,  
            "max_posts_per_day":    3,
        }
        
    async def on_startup(self):
        await self._init_write_client()
        await self._init_read_client()
        
    async def on_shutdown(self):
        pass
    
    async def _init_write_client(self):
        api_key = os.getenv("X_API_KEY")
        api_secret = os.getenv("X_API_SECRET")
        access_tok = os.getenv("X_ACCESS_TOKEN")
        access_sec = os.getenv("X_ACCESS_TOKEN_SECRET")

        if not all([api_key, api_secret, access_tok, access_sec]):
            print("[X] Missing API credentials - posting disabled. "
                  "Set X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET.")
            return

        try:
            self._tweepy = tweepy.Client(
                consumer_key = api_key,
                consumer_secret = api_secret,
                access_token = access_tok,
                access_token_secret = access_sec,
                wait_on_rate_limit  = False  
            )
            
            me = self._tweepy.get_me()
            if me and me.data:
                self._own_username = me.data.username
                print(f"[X] Write client authenticated as @{self._own_username}.")
            else:
                print("[X] Write client auth failed - check credentials.")
                self._tweepy = None

        except tweepy.errors.TweepyException as e:
            print(f"[X] Tweepy init error: {e}")
            self._tweepy = None
    
    async def _init_read_client(self):
        username = os.getenv("X_SCRAPE_USERNAME")
        password = os.getenv("X_SCRAPE_PASSWORD")
        email    = os.getenv("X_SCRAPE_EMAIL")
        cookie_str = os.getenv("X_COOKIES", "")
        if not all([username, password, email]):
            print("[X] Missing scrape credentials (X_SCRAPE_USERNAME, X_SCRAPE_PASSWORD, "
                  "X_SCRAPE_EMAIL) - read/search disabled.")
            return
        
        try:
            self._scraper = TwscrapeAPI()
            cookies: dict | None = None
            if cookie_str:
                cookies = _parse_cookie_string(cookie_str)
                print(f"[X] Loaded {len(cookies)} cookies from X_COOKIES.")
                
            await self._scraper.pool.add_account(
                username = username,
                password = password,
                email = email,
                email_password = password,
                cookies=json.dumps(cookies) if cookies else None
            )
            
            try:
                await self._scraper.pool.login_all()
            except Exception as login_err:
                print(f"[X] login_all() error: {login_err}")
                if "parse scripts" in str(login_err).lower() or "Failed to parse" in str(login_err):
                    print(
                        "[X] twscrape cannot parse X's JS bundles (they changed again).\n"
                        "    Fix: pip install -U twscrape\n"
                        "    If already on latest, file an issue: https://github.com/vladkens/twscrape/issues"
                    )
                if not cookies:
                    self._scraper = None
                    return
                print("[X] Proceeding with cookies despite login error.")
            
            accounts = await self._scraper.pool.get_all()
            usable   = [a for a in accounts if getattr(a, "active", False)]
            logged   = [a for a in usable if getattr(a, "logged_in", False)]

            if not logged:
                print(
                    f"[X] Account is active but not logged in (logged_in=0).\n"
                    f"    Requests will fail until this is resolved.\n"
                    f"    Most likely cause: twscrape needs updating.\n"
                    f"    Run: pip install -U twscrape  then delete accounts.db and restart."
                )
                # Still keep _scraper set — some search endpoints work with guest auth
            else:
                print(f"[X] Scrape client ready (@{username}). logged_in=1")

        except Exception as e:
            print(f"[X] twscrape init error: {e}")
            self._scraper = None
    
    async def fetch_feed(self, limit: int = 20) -> list[Post]:
        if not self._scraper:
            return []
        
        try:
            accounts = await self._scraper.pool.get_all()
            if not any(getattr(a, "logged_in", False) for a in accounts):
                print("[X] Skipping feed fetch — account not logged in (logged_in=0). "
                      "Run: pip install -U twscrape, delete accounts.db, restart.")
                return []
        except Exception:
            pass
        
        posts   = []
        per_topic = max(1, min(SEARCH_LIMIT, limit // max(len(WATCHED_TOPICS), 1)))
        
        for topic in WATCHED_TOPICS:
            if len(posts) >= limit:
                break
            
            try:
                query=f"{topic} lang:en -is:retweet min_faves{MIN_LIKES}"
                tweets = await gather(
                    self._scraper.search(query, limit=per_topic)
                )
                for tweet in tweets:
                    post = self._tweet_to_post(tweet)
                    if post:
                        posts.append(post)
            
            except Exception as e:
                print(f"[X] Search error for '{topic}': {e}")
        
        return posts

    async def fetch_thread(self, post_id: str, max_comments: int = 10) -> list[Post]:
        if not self._scraper:
            return []

        results = []
        try:
            tweet = await self._scraper.tweet_details(int(post_id))
            if tweet:
                post = self._tweet_to_post(tweet)
                if post:
                    results.append(post)
                    
            query = f"conversation_id:{post_id} lang:en"
            replies = await gather(
                self._scraper.search(query, limit=max_comments)
            )
            
            for reply in replies:
                rpost = self._tweet_to_post(reply, parent_id=post_id, depth=1)
                if rpost:
                    results.append(rpost)
            
        except Exception as e:
            print(f"[X] Thread fetch error for {post_id}: {e}")

        return results
    
    async def post_reply(self, post_id: str, content: str) -> PostResult:
        if not self._tweepy:
            return PostResult(success=False, error="Write client not initialized.")

        content = _truncate_to_limit(content)
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._tweepy.create_tweet(
                    text = content, 
                    in_reply_to_tweet_id= int(post_id)
                )
            )
            
            if result and result.data:
                tweet_id = result.data["id"]
                url      = f"https://x.com/{self._own_username}/status/{tweet_id}"
                self._last_post_time = time.time()
                print(f"[X] Reply posted: {url}")
                return PostResult(success=True, post_id=str(tweet_id), url=url)
            else:
                return PostResult(success=False, error="Empty response from API.")
        
        except tweepy.errors.TooManyRequests:
            return PostResult(success=False,
                              error="Rate limited by X API. Try again later.")
        except tweepy.errors.Forbidden as e:
            return PostResult(success=False, error=f"Forbidden: {e}")
        except tweepy.errors.TweepyException as e:
            return PostResult(success=False, error=str(e))
        
    async def post_original(self, title: str, content: str, url: str | None = None) -> PostResult:
        if not self._tweepy:
            return PostResult(success=False, error="Write client not initialized.")

        text = content
        if url:
            text = _truncate_to_limit(content, reserve = 25) + f"\n{url}"
        else:
            text = _truncate_to_limit(content)
            
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                lambda: self._tweepy.create_tweet(text = text) # type: ignore
            )
            
            if result and result.data:
                tweet_id = result.data["id"]
                url_out  = f"https://x.com/{self._own_username}/status/{tweet_id}"
                self._last_post_time = time.time()
                print(f"[X] Tweet posted: {url_out}")
                return PostResult(success=True, post_id=str(tweet_id), url=url_out)
            else:
                return PostResult(success=False, error="Empty response from API.")

        except tweepy.errors.TooManyRequests:
            return PostResult(success=False, error="Rate limited.")
        except tweepy.errors.TweepyException as e:
            return PostResult(success=False, error=str(e))
        
    async def get_own_posts(self, limit: int = 10) -> list[Post]:
        if not self._scraper or not self._own_username:
            return []
        try:
            user_tweets = await gather(
                self._scraper.user_tweets(
                    await self._get_own_user_id(), limit=limit
                )
            )
            return [p for p in
                    (self._tweet_to_post(t) for t in user_tweets)
                    if p is not None]
        except Exception as e:
            print(f"[X] Own posts fetch error: {e}")
            return []
        
    async def _get_own_user_id(self) -> int:
        user = await self._scraper.user_by_login(self._own_username) # type: ignore
        if user:
            return user.id
        raise ValueError(f"Could not resolve @{self._own_username} to a user ID.")
    
    def _tweet_to_post(self, tweet, parent_id: Optional[str] = None, depth: int = 0) -> Optional[Post]:
        try:
            return Post(
                platform = "x",
                post_id = str(tweet.id),
                title = "",
                body  = tweet.rawContent or "",
                url = tweet.url or f"https://x.com/i/status/{tweet.id}",
                author = tweet.user.username if tweet.user else "[unknown]",
                score = tweet.likeCount or 0,
                comment_count = tweet.replyCount or 0,
                parent_id = parent_id,
                depth = depth,
            )
        except Exception:
            return None

def _truncate_to_limit(text: str, limit: int = 280, reserve: int = 0) -> str:
    max_chars = limit - reserve
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars - 1].rsplit(" ", 1)[0]
    return truncated + "…"