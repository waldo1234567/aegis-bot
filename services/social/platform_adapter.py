from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Post:
    platform: str
    post_id: str
    title: str         
    body: str          
    url: str
    author: str
    score: int          
    comment_count: int
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat())
    parent_id: Optional[str] = None   
    depth: int = 0
    
@dataclass
class PostResult:
    success: bool
    post_id: str = ""  
    url: str = ""
    error: str = ""

class PlatformAdapter(ABC):
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Short identifier: 'hackernews', 'reddit', etc."""
        ...
    
    @abstractmethod
    async def fetch_feed(self, limit: int = 20) -> list[Post]:
        """
        Fetch recent top/new/rising posts from the platform.
        Returns a flat list — threading is handled by fetch_thread().
        """
        ...

    @abstractmethod
    async def fetch_thread(self, post_id: str, max_comments: int = 10) -> list[Post]:
        """
        Retrieve the comment thread for a given post.
        Returns the original post + top-level comments as a flat list.
        """
        ...

    @abstractmethod
    async def post_reply(self, post_id: str, content: str) -> PostResult:
        """
        Post a reply to an existing post or comment.
        post_id: the platform's identifier for what we're replying to.
        """
        ...

    @abstractmethod
    async def post_original(self, title: str, content: str,
                            url: Optional[str] = None) -> PostResult:
        """
        Submit an original post.
        url: if provided, submit as a link post instead of text.
        """
        ...

    @abstractmethod
    async def get_own_posts(self, limit: int = 10) -> list[Post]:
        """Retrieve Aegis's own recent posts (for context, avoiding repetition)."""
        ...
    
    async def on_startup(self):
        """Called once when the social shard starts. Use for auth, session init."""
        pass

    async def on_shutdown(self):
        """Called when the social shard shuts down cleanly."""
        pass

    def rate_limit_config(self) -> dict:
        """
        Return platform-specific rate limit settings.
        Override in subclass to customize.
        """
        return {
            "max_posts_per_hour":   2,
            "min_seconds_between":  300, 
            "max_posts_per_day":    8,
        }