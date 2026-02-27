import os
import asyncpraw
from typing import Optional, List
from services.social.platform_adapter import PlatformAdapter, Post, PostResult

class RedditAdapter(PlatformAdapter):
    def __init__(self):
        self.reddit = None
        self.subreddit_list = ["SubredditName1", "SubredditName2"] # This should be configured

    @property
    def platform_name(self) -> str:
        return "reddit"

    async def on_startup(self):
        print("[RedditAdapter] Initializing...")
        try:
            self.reddit = asyncpraw.Reddit(
                client_id=os.getenv("REDDIT_CLIENT_ID"),
                client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
                user_agent=os.getenv("REDDIT_USER_AGENT"),
                username=os.getenv("REDDIT_USERNAME"),
                password=os.getenv("REDDIT_PASSWORD"),
                check_for_async=False
            )
            print("[RedditAdapter] Successfully initialized and authenticated.")
        except Exception as e:
            print(f"[RedditAdapter] Error during initialization: {e}")
            self.reddit = None

    async def fetch_feed(self, limit: int = 20) -> List[Post]:
        if not self.reddit:
            return []
        
        posts = []
        try:
            subreddit = await self.reddit.subreddit("all")
            async for submission in subreddit.hot(limit=limit):
                posts.append(Post(
                    platform=self.platform_name,
                    post_id=submission.id,
                    title=submission.title,
                    body=submission.selftext,
                    url=submission.url,
                    author=str(submission.author),
                    score=submission.score,
                    comment_count=submission.num_comments
                ))
            return posts
        except Exception as e:
            print(f"[RedditAdapter] Error fetching feed: {e}")
            return []

    async def fetch_thread(self, post_id: str, max_comments: int = 10) -> List[Post]:
        if not self.reddit:
            return []
        
        thread_posts = []
        try:
            submission = await self.reddit.submission(id=post_id)
            thread_posts.append(Post(
                platform=self.platform_name,
                post_id=submission.id,
                title=submission.title,
                body=submission.selftext,
                url=submission.url,
                author=str(submission.author),
                score=submission.score,
                comment_count=submission.num_comments
            ))

            await submission.comments.replace_more(limit=0)
            comments = submission.comments.list()
            for i, comment in enumerate(comments):
                if i >= max_comments:
                    break
                thread_posts.append(Post(
                    platform=self.platform_name,
                    post_id=comment.id,
                    title="",
                    body=comment.body,
                    url=f"https://www.reddit.com{comment.permalink}",
                    author=str(comment.author),
                    score=comment.score,
                    comment_count=len(comment.replies),
                    parent_id=comment.parent_id,
                    depth=comment.depth
                ))
            return thread_posts
        except Exception as e:
            print(f"[RedditAdapter] Error fetching thread {post_id}: {e}")
            return []

    async def post_reply(self, post_id: str, content: str) -> PostResult:
        if not self.reddit:
            return PostResult(success=False, error="Reddit client not initialized.")
        
        try:
            # asyncpraw can handle both submission and comment IDs with the fullname
            redditor_object = await self.reddit.get_info(fullnames=[post_id])
            if not redditor_object:
                 return PostResult(success=False, error=f"Could not find object with ID {post_id}")
            
            comment = await redditor_object[0].reply(content)
            return PostResult(success=True, post_id=comment.id, url=f"https://www.reddit.com{comment.permalink}")
        except Exception as e:
            print(f"[RedditAdapter] Error posting reply to {post_id}: {e}")
            return PostResult(success=False, error=str(e))

    async def post_original(self, title: str, content: str, url: Optional[str] = None) -> PostResult:
        # This needs a target subreddit. For now, let's assume a default one.
        # This is a major simplification and would need a better strategy.
        target_subreddit = "testingground4bots"
        if not self.reddit:
            return PostResult(success=False, error="Reddit client not initialized.")
        
        try:
            subreddit = await self.reddit.subreddit(target_subreddit)
            if url:
                submission = await subreddit.submit(title, url=url)
            else:
                submission = await subreddit.submit(title, selftext=content)
            return PostResult(success=True, post_id=submission.id, url=submission.permalink)
        except Exception as e:
            print(f"[RedditAdapter] Error posting original content: {e}")
            return PostResult(success=False, error=str(e))

    async def get_own_posts(self, limit: int = 10) -> List[Post]:
        if not self.reddit or not self.reddit.user.me:
            return []
        
        posts = []
        try:
            redditor = await self.reddit.user.me()
            async for comment in redditor.comments.new(limit=limit):
                posts.append(Post(
                    platform=self.platform_name,
                    post_id=comment.id,
                    title="",
                    body=comment.body,
                    url=f"https://www.reddit.com{comment.permalink}",
                    author=str(redditor),
                    score=comment.score,
                    comment_count=0, # Hard to get reply count efficiently
                    parent_id=comment.parent_id
                ))
            return posts
        except Exception as e:
            print(f"[RedditAdapter] Error getting own posts: {e}")
            return []

    def rate_limit_config(self) -> dict:
        return {
            "max_posts_per_hour": 5,
            "min_seconds_between": 60,
            "max_posts_per_day": 50,
        }
