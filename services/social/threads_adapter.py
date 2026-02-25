import asyncio
import os
import time
from typing import Optional

import httpx
from dotenv import load_dotenv

from services.social.platform_adapter import PlatformAdapter, Post, PostResult

load_dotenv()

THREADS_API  = "https://graph.threads.net/v1.0"
FETCH_TIMEOUT = 15

WATCHED_KEYWORDS = [
    "AI",
    "ChatGPT",
    "coding",
    "startup",
    "tech",
    "programming",
    "machine learning",
    "software",
]
POST_FIELDS="id,text,timestamp,username,like_count,reply_count,permalink"

class ThreadsAdapter(PlatformAdapter):
    def __init__(self):
        self._token:   str = os.getenv("THREADS_ACCESS_TOKEN", "")
        self._user_id: str = os.getenv("THREADS_USER_ID", "")
        self._username: str = ""
        self._client:  Optional[httpx.AsyncClient] = None
        self._last_post_time: float = 0.0
    
    @property
    def platform_name(self) -> str:
        return "threads"

    def rate_limit_config(self) -> dict:
        return {
            "max_posts_per_hour":   3,
            "min_seconds_between":  300,  
            "max_posts_per_day":    10,
        }
        
    async def on_startup(self):
        if not self._token or not self._user_id:
            print(
                "[Threads] Missing credentials.\n"
                "  Set THREADS_ACCESS_TOKEN and THREADS_USER_ID in .env\n"
            )
            return
        
        self._client = httpx.AsyncClient(
            base_url= THREADS_API,
            params   = {"access_token": self._token},
            timeout  = FETCH_TIMEOUT,
            headers  = {"Accept": "application/json"},
        )
        
        try:
            resp = await self._client.get("/me", params={"fields": "id,username"})
            data = resp.json()
            if "error" in data:
                print(f"[Threads] Auth failed: {data['error'].get('message', data)}")
                await self._client.aclose()
                self._client = None
                return
            username = data.get("username", "unknown")
            self._username = username
            print(f"[Threads] Authenticated as @{username} (id: {self._user_id}).")
        except Exception as e:
            print(f"[Threads] Startup error: {e}")
            self._client = None
    
    async def on_shutdown(self):
        if self._client:
            await self._client.aclose()
    
    async def fetch_feed(self, limit: int = 20) -> list[Post]:
        if not self._client:
            return []

        posts = []
        per_keyword = max(1, limit // max(len(WATCHED_KEYWORDS), 1))

        for keyword in WATCHED_KEYWORDS:
            if len(posts) >= limit:
                break
            try:
                resp = await self._client.get(
                    "/threads/keyword_search",
                    params={
                        "q":      keyword,
                        "limit":  per_keyword,
                        "fields": POST_FIELDS,
                    }
                )
                data = resp.json()

                if "error" in data:
                    err_msg = data["error"].get("message", str(data))
                    print(f"[Threads] Search error for '{keyword}': {err_msg}")
                    continue

                for item in data.get("data", []):
                    post = self._item_to_post(item)
                    if post:
                        posts.append(post)

            except Exception as e:
                print(f"[Threads] Search error for '{keyword}': {e}")

        return posts
    
    async def fetch_thread(self, post_id: str, max_comments: int = 10) -> list[Post]:
        if not self._client:
            return []
        
        results = []
        try:
            resp = await self._client.get(
                f"/{post_id}",
                params={"fields": POST_FIELDS}
            )
            data = resp.json()
            if "error" not in data:
                post = self._item_to_post(data)
                if post:
                    results.append(post)
                    
            resp = await self._client.get(
                f"/{post_id}/replies",
                params={
                    "fields": POST_FIELDS,
                    "limit":  max_comments,
                }
            )
            
            data = resp.json()
            for item in data.get("data", []):
                reply = self._item_to_post(item, parent_id=post_id, depth=1)
                if reply:
                    results.append(reply)

        except Exception as e:
            print(f"[Threads] Thread fetch error for {post_id}: {e}")

        return results

    async def post_reply(self, post_id: str, content: str) -> PostResult:
        if not self._client:
            return PostResult(success=False, error="Not authenticated.")
        
        container_id = await self._create_container(content, reply_to_id=post_id)
        if not container_id:
            return PostResult(success=False, error="Failed to create reply container.")
        
        return await self._publish_container(container_id)
    
    async def post_original(self, title: str, content: str, url: Optional[str] = None) -> PostResult:
        if not self._client:
            return PostResult(success=False, error="Not authenticated.")
        
        text = content
        if url:
            text = f"{content}\n\n{url}"
        
        container_id = await self._create_container(text)
        if not container_id:
            return PostResult(success=False, error="Failed to create post container.")

        return await self._publish_container(container_id)
    
    async def get_own_posts(self, limit: int = 10) -> list[Post]:
        if not self._client:
            return []
        
        try:
            resp = await self._client.get(
                f"/{self._user_id}/threads",
                params={
                    "fields": POST_FIELDS,
                    "limit":  limit,
                }
            )
            
            data = resp.json()
            
            return [
                p for p in (self._item_to_post(item) for item in data.get("data", []))
                if p is not None
            ]
        except Exception as e:
            print(f"[Threads] Own posts fetch error: {e}")
            return []
    
    async def _create_container(self, text: str, reply_to_id: Optional[str] = None) -> Optional[str]:
        try:
            params : dict = {
                "media_type": "TEXT",
                "text": text,
            }
            
            if reply_to_id:
                params["reply_to_id"] = reply_to_id
            
            resp = await self._client.post(
                f"/{self._user_id}/threads",
                params=params
            )
            
            data = resp.json()
            
            if "error" in data:
                print(f"[Threads] Container creation failed: "
                      f"{data['error'].get('message', data)}")
                return None
            
            return data.get("id")
        
        except Exception as e:
            print(f"[Threads] Container creation error: {e}")
            return None
    
    async def _publish_container(self, container_id : str) -> PostResult:
        try:
            await asyncio.sleep(1)

            resp = await self._client.post(
                f"/{self._user_id}/threads_publish",
                params={"creation_id": container_id}
            )
            data = resp.json()
            
            if "error" in data:
                msg = data["error"].get("message", str(data))
                return PostResult(success=False, error=f"Publish failed: {msg}")

            thread_id = data.get("id", "")
            
            url = ""
            try:
                await asyncio.sleep(2)
                fields_resp = await self._client.get(
                    f"/{thread_id}",
                    params={"fields": "permalink"}
                )
                fields_data = fields_resp.json()
                url = fields_data.get("permalink", "")
            except Exception as e:
                print(f"[Threads] Warning: Could not fetch permalink: {e}")
                
            if not url:
                username  = self._username or self._user_id
                url = f"https://www.threads.net/@{username}/post/{thread_id}"
            
            self._last_post_time = time.time()
            print(f"[Threads] Posted successfully: {url}")
            return PostResult(success=True, post_id=thread_id, url=url)
        except Exception as e:
            return PostResult(success=False, error=str(e))
        
    
    def _item_to_post(self, item: dict, parent_id: Optional[str] = None,
                      depth: int = 0) -> Optional[Post]:
        
        try:
            post_id = item.get("id", "")
            if not post_id:
                return None
            
            return Post(
                platform = "threads",
                post_id = post_id,
                title = "",   
                body = item.get("text", ""),
                url = item.get("permalink", f"https://www.threads.net/post/{post_id}"),
                author = item.get("username", "[unknown]"),
                score = item.get("like_count", 0),
                comment_count = item.get("reply_count", 0),
                parent_id = parent_id,
                depth= depth,
            )
        except Exception:
            return None
            
