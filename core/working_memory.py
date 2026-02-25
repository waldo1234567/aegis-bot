from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

COMPRESS_THRESHOLD = 18_000   
KEEP_RECENT_ENTRIES = 3   
CHARS_PER_TOKEN = 4

@dataclass
class MemoryEntry:
    kind: str
    source: str
    content: str
    depth: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    @property
    def token_estimate(self) -> int:
        return len(self.content) // CHARS_PER_TOKEN
    
    def to_block(self) -> str:
        return f"[{self.kind.upper()} | {self.source} | depth {self.depth}]:\n{self.content}"
    

class WorkingMemory:
    def __init__(self, topic: str, llm: Any):
        self.topic = topic
        self.llm = llm
        self.entries: list[MemoryEntry] = []
        self.compressed: str = ""       
        self.compressed_token_estimate = 0
        self._compression_count = 0
        
    def add_tool_result(self, tool_name: str, content: str, depth: int):
        self._append(MemoryEntry(
            kind="tool_result", 
            source=tool_name,
            content=str(content),
            depth=depth
        ))
        
    def add_thought(self, content: str, depth: int):
        self._append(MemoryEntry(
            kind="thought", 
            source="internal",
            content=str(content), 
            depth=depth
        ))

    def _append(self, entry: MemoryEntry):
        self.entries.append(entry)
        if self.total_tokens > COMPRESS_THRESHOLD:
            self._compress()
    
    @property
    def total_tokens(self) -> int:
        raw = sum(e.token_estimate for e in self.entries)
        return raw + self.compressed_token_estimate

    def render(self) -> str:
        sections = [f"Topic: {self.topic}\n"]
        
        if self.compressed:
            sections.append(
                f"[COMPRESSED PRIOR FINDINGS ({self._compression_count} compression(s))]:\n"
                f"{self.compressed}"
            )
            
        if self.entries:
            sections.append("\n[RECENT RAW DATA (verbatim)]:")
            for entry in self.entries:
                sections.append(entry.to_block())

        return "\n\n".join(sections)
    
    def render_for_synthesis(self) -> str:
        return self.render()
    
    def summary_stats(self) -> str:
        return (f"~{self.total_tokens:,} tokens | "
                f"{len(self.entries)} raw entries | "
                f"{self._compression_count} compression(s)")
        
    
    def _compress(self):
        if len(self.entries) <= KEEP_RECENT_ENTRIES:
            return

        to_compress = self.entries[:-KEEP_RECENT_ENTRIES]
        keep = self.entries[-KEEP_RECENT_ENTRIES:]
        
        raw_block = "\n\n".join(e.to_block() for e in to_compress)
        existing  = f"\n\nPrevious summary:\n{self.compressed}" if self.compressed else ""

        print(f" [WorkingMemory] Compressing {len(to_compress)} entries "
              f"(~{sum(e.token_estimate for e in to_compress):,} tokens)...")
        
        prompt = f"""
        You are the memory compressor for Aegis, a cynical AI researcher.

        Compress the following research notes into a dense, fact-focused summary.
        Preserve: specific URLs, names, numbers, code snippets, and Aegis's conclusions.
        Remove: filler, repeated tool preambles, raw HTML noise.
        Keep it under 500 words. Write in third-person past tense ("Aegis found...", "The page showed...").
        {existing}

        RESEARCH NOTES TO COMPRESS:
        {raw_block}

        COMPRESSED SUMMARY:"""
        
        try:
            response = self.llm.invoke(prompt)
            summary = str(response.content).strip()
            
            if self.compressed:
                self.compressed = f"{self.compressed}\n\n[Compression {self._compression_count + 1}]:\n{summary}"
            else:
                self.compressed = summary

            self.compressed_token_estimate = len(self.compressed) // CHARS_PER_TOKEN
            self._compression_count += 1
            self.entries = keep
            print(f" [WorkingMemory] Compressed. "
                  f"Scratchpad now ~{self.total_tokens:,} tokens.")
        
        except Exception as e:
            print(f" [WorkingMemory] Compression failed: {e}. Keeping raw entries.")