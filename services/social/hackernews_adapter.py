import asyncio
import os
import re
import time
from typing import Optional

import httpx
from dotenv import load_dotenv

from services.social.platform_adapter import PlatformAdapter, Post, PostResult

load_dotenv()

HN_BASE = "https://hacker-news.firebaseio.com/v0"
HN_WEB = "https://news.ycombinator.com"
FETCH_TIMEOUT  = 15

class HackerNewsAdapter(PlatformAdapter):
    def __init__(self):
        self._username  = os.getenv("HN_USERNAME", "")
        self._password  = os.getenv("HN_PASSWORD", "")
        self._session:  Optional[httpx.AsyncClient] = None
        self._logged_in = False
        self._last_post_time: float = 0.0
    
    @property
    def platform_name(self) -> str:
        return "hackernews"
    
    def rate_limit_config(self) -> dict:
        return {
            "max_posts_per_hour": 1, 
            "min_seconds_between": 600,
            "max_posts_per_day": 4,
        }
        

    async def on_startup(self):
        self._session = httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
            timeout=FETCH_TIMEOUT
        )
        if self._username and self._password:
            await self._login()
        else:
            print("[HN] No credentials set - read-only mode.")
    
    async def on_shutdown(self):
        if self._session:
            await self._session.aclose()
    
    async def _login(self):
        if not self._session:
            return
        try:
            resp = await self._session.post(
                f"{HN_WEB}/login",
                data={"acct": self._username, "pw": self._password, "goto": "news"},
            )
            body = resp.text

            if "Bad login" in body:
                print(f"[HN] Login failed: bad credentials. Check HN_USERNAME / HN_PASSWORD.")
                self._logged_in = False
                return

            if f"user?id={self._username}" in body or "logout" in body:
                self._logged_in = True
                print(f"[HN] Logged in as {self._username}.")
            else:
                # Ambiguous - verify with a follow-up auth check
                self._logged_in = await self._check_auth_status()
                if self._logged_in:
                    print(f"[HN] Logged in as {self._username} (verified via auth check).")
                else:
                    print("[HN] Login failed: response was ambiguous and auth check failed.")

        except Exception as e:
            print(f"[HN] Login error: {e}")
            
    async def _check_auth_status(self) -> bool:
        if not self._session:
            return False
        try:
            resp = await self._session.get(
                f"{HN_WEB}/submit",
                follow_redirects=False
            )
            if resp.status_code == 302:
                location = resp.headers.get("location", "")
                if "login" in location:
                    print("[HN] Auth check: 302 to login - not authenticated.")
                    return False
            if resp.status_code == 200 and "title" in resp.text.lower():
                return True
            return False
        except Exception as e:
            print(f"[HN] Auth check error: {e}")
            return False
    
    async def _ensure_session(self) -> bool:
        if not self._session:
            return False
        if not self._logged_in:
            await self._login()
            return self._logged_in
        still_valid = await self._check_auth_status()
        if not still_valid:
            print("[HN] Session expired - re-authenticating...")
            self._logged_in = False
            await self._login()
        return self._logged_in
    
    async def _extract_form_token(self, page_url: str) -> tuple[str | None, str | None]:
        if not self._session:
            return None, None
        try:
            resp = await self._session.get(page_url, follow_redirects=False)
            if resp.status_code == 302:
                location = resp.headers.get("location", "(no location header)")
                print(f"[HN] Reply page redirected to: {location} — session dead.")
                return None, None

            if resp.status_code != 200:
                print(f"[HN] Unexpected {resp.status_code} on {page_url}")
                return None, None

            html = resp.text

            for field in ("hmac", "fnid"):
                match = re.search(rf'name="{field}"\s+value="([^"]+)"', html)
                if match:
                    return field, match.group(1)

            snippet = " ".join(html[:800].split())
            print(
                f"[HN] Form token not found.\n"
                f"  URL    : {page_url}\n"
                f"  Status : {resp.status_code}\n"
                f"  HTML len: {len(html)} chars\n"
                f"  Snippet: {snippet[:400] if snippet else '(empty — page returned no content)'}"
            )
            return None, None

        except Exception as e:
            print(f"[HN] Form token fetch error: {e}")
            return None, None
    
    async def fetch_feed(self, limit: int = 20) -> list[Post]:
        if not self._session:
            return []

        try:
            resp = await self._session.get(f"{HN_BASE}/topstories.json")
            story_ids = resp.json()[:limit]
            
            posts = await asyncio.gather(*[
                self._fetch_item(sid) for sid in story_ids
            ], return_exceptions=True)
            
            return [p for p in posts if isinstance(p, Post)]

        except Exception as e:
            print(f"[HN] Feed fetch error: {e}")
            return []
    
    async def _fetch_item(self, item_id: int) -> Optional[Post]:
        if not self._session:
            return None
        try:
            resp = await self._session.get(f"{HN_BASE}/item/{item_id}.json")
            data = resp.json()
            if not data or data.get("dead") or data.get("deleted"):
                return None
            
            return Post(
                platform = "hackernews",
                post_id = str(data["id"]),
                title = data.get("title", ""),
                body = data.get("text", "") or data.get("url", ""),
                url = f"{HN_WEB}/item?id={data['id']}",
                author = data.get("by", "[deleted]"),
                score = data.get("score", 0),
                comment_count = data.get("descendants", 0),
                parent_id = str(data["parent"]) if "parent" in data else None,
                depth = 0
            )
        except Exception:
            return None

    async def fetch_thread(self, post_id: str, max_comments: int = 10) -> list[Post]:
        if not self._session:
            return []
        try:
            resp = await self._session.get(f"{HN_BASE}/item/{post_id}.json")
            data = resp.json()
            if not data:
                return []

            results: list[Post] = []
            story = await self._fetch_item(int(post_id))
            if story:
                results.append(story)

            kids = (data.get("kids") or [])[:max_comments]
            comments = await asyncio.gather(*[
                self._fetch_item(kid) for kid in kids
            ], return_exceptions=True)

            results.extend(c for c in comments if isinstance(c, Post))
            return results

        except Exception as e:
            print(f"[HN] Thread fetch error: {e}")
            return []
        
    async def _item_is_replyable(self, post_id: str) -> tuple[bool, str]:
        try:
            resp = await self._session.get(
                f"{HN_BASE}/item/{post_id}.json",
                follow_redirects=True
            )
            data = resp.json()

            if data is None:
                return False, f"Item {post_id} does not exist on HN."
            if data.get("deleted"):
                return False, f"Item {post_id} is deleted."
            if data.get("dead"):
                return False, f"Item {post_id} is dead (flagged/killed)."
            if "by" not in data:
                # Item exists but has no author — effectively dead
                return False, f"Item {post_id} has no author (likely dead)."

            return True, ""

        except Exception as e:
            # If Firebase check fails, don't block the attempt — log and continue
            print(f"[HN] Liveness check failed for {post_id}: {e} — proceeding anyway.")
            return True, ""
        
    async def post_reply(self, post_id: str, content: str) -> PostResult:
        if not await self._ensure_session():
            return PostResult(success=False, error="Not logged in / session invalid.")
        
        alive, reason = await self._item_is_replyable(post_id)
        if not alive:
            return PostResult(success=False, error=reason)

        try:
            field, token = await self._extract_form_token(
                f"{HN_WEB}/reply?id={post_id}"
            )
            if not field or not token:
                return PostResult(success=False,
                                  error="Could not extract form token from reply page.")

            resp = await self._session.post(
                f"{HN_WEB}/comment",
                data={field: token, "fnop": "reply", "text": content}
            )

            if resp.status_code in (200, 302):
                self._last_post_time = time.time()
                print(f"[HN] Reply posted to {post_id}.")
                return PostResult(
                    success=True,
                    post_id=post_id,
                    url=f"{HN_WEB}/item?id={post_id}"
                )
            else:
                return PostResult(success=False, error=f"HTTP {resp.status_code}")

        except Exception as e:
            return PostResult(success=False, error=str(e))
    
    async def post_original(self, title: str, content: str, url: str | None = None) -> PostResult:
        if not await self._ensure_session():
            return PostResult(success=False, error="Not logged in / session invalid.")

        try:
            field, token = await self._extract_form_token(f"{HN_WEB}/submit")
            if not field or not token:
                return PostResult(success=False,
                                  error="Could not extract form token from submit page.")

            payload = {field: token, "fnop": "submit-page", "title": title}
            if url:
                payload["url"] = url
            else:
                payload["text"] = content

            resp = await self._session.post(
                f"{HN_WEB}/r",
                data=payload,
                follow_redirects=True
            )
            final_url = str(resp.url)
            body = resp.text
            
            if "item?id=" in final_url:
                item_id = final_url.split("item?id=")[-1].split("&")[0]
                item_url = f"{HN_WEB}/item?id={item_id}"
                self._last_post_time = time.time()
                print(f"[HN] Post submitted successfully: {item_url}")
                return PostResult(success=True, post_id=item_id, url=item_url)
            
            for error_phrase in [
                "that's the same as",   
                "you're posting too fast",
                "you have to be logged in",
                "delay between submissions",
            ]:
                if error_phrase.lower() in body.lower():
                    return PostResult(success=False,
                                      error=f"HN rejected post: '{error_phrase}'")

            if "submit" in final_url or resp.status_code != 200:
                snippet = " ".join(body[:400].split())
                print(f"[HN] Post may have failed. Final URL: {final_url}\n"
                      f"  Body snippet: {snippet[:200]}")
                return PostResult(success=False,
                                  error=f"Post did not create an item. Landed on: {final_url}")

            print(f"[HN] Ambiguous response. Final URL: {final_url}")
            return PostResult(success=False,
                              error=f"Could not confirm post was created. Final URL: {final_url}")

        except Exception as e:
            return PostResult(success=False, error=str(e))
        
    async def get_own_posts(self, limit: int = 10) -> list[Post]:
        if not self._session or not self._username:
            return []
        try:
            resp = await self._session.get(
                f"{HN_BASE}/user/{self._username}.json"
            )
            data = resp.json()
            submitted = (data.get("submitted") or [])[:limit]
            posts = await asyncio.gather(*[
                self._fetch_item(pid) for pid in submitted
            ], return_exceptions=True)
            return [p for p in posts if isinstance(p, Post)]
        except Exception as e:
            print(f"[HN] Own posts fetch error: {e}")
            return []
        