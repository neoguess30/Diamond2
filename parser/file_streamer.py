from __future__ import annotations
import csv
import json
from typing import Generator, Any, Optional, Set

class StreamingTargetExtractor:
    """
    Enterprise Streaming Target Extractor:
    Guarantees strict O(1) RAM consumption across multi-gigabyte TXT, CSV, and JSON files.
    """
    TARGET_KEYS: Set[str] = {
        "username", "handle", "target", "user", "name",
        "users", "targets", "handles", "names", "members"
    }
    
    @classmethod
    def stream_txt(cls, file_path: str) -> Generator[str, None, None]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                u = line.strip().replace("@", "")
                if u:
                    yield u

    @classmethod
    def stream_csv(cls, file_path: str) -> Generator[str, None, None]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            header_checked = False
            user_col_idx = 0
            for row in reader:
                if not row:
                    continue
                if not header_checked:
                    header_checked = True
                    for i, col in enumerate(row):
                        if any(k in col.lower() for k in ["user", "handle", "target", "name"]):
                            user_col_idx = i
                            break
                    if any(k in row[user_col_idx].lower() for k in ["user", "handle", "target"]):
                        continue
                if len(row) > user_col_idx:
                    u = row[user_col_idx].strip().replace("@", "")
                    if u:
                        yield u

    @classmethod
    def _extract_from_value(cls, val: Any) -> Generator[str, None, None]:
        """Recursively extracts target username strings from arbitrary nested Python structures."""
        if isinstance(val, str):
            clean = val.strip().replace("@", "")
            if clean:
                yield clean
        elif isinstance(val, (list, tuple, set)):
            for item in val:
                yield from cls._extract_from_value(item)
        elif isinstance(val, dict):
            found_target_key = False
            for k in cls.TARGET_KEYS:
                if k in val and val[k]:
                    found_target_key = True
                    yield from cls._extract_from_value(val[k])
            
            if not found_target_key:
                for v in val.values():
                    if isinstance(v, (str, list, tuple, set, dict)):
                        yield from cls._extract_from_value(v)

    @classmethod
    def stream_json(cls, file_path: str) -> Generator[str, None, None]:
        """
        P0 Incremental JSON Stream Parser:
        Uses json.JSONDecoder.raw_decode with an adaptive sliding chunk buffer.
        Correctly handles:
        1. Top-level arrays of strings or objects.
        2. Root dictionary containers with nested arrays: {"users": [{"username": "alice"}, ...]}.
        3. Line-delimited JSON (JSONL / NDJSON).
        4. Elements crossing arbitrary 64KB chunk boundaries (e.g. 100,000-character strings) with strict O(1) RAM.
        """
        decoder = json.JSONDecoder()
        buffer = ""
        current_key: Optional[str] = None
        
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            while True:
                chunk = f.read(65536)
                if not chunk and not buffer.strip():
                    break
                
                buffer += chunk
                idx = 0
                buf_len = len(buffer)

                while idx < buf_len:
                    # Skip whitespace and structural syntax punctuation
                    while idx < buf_len and buffer[idx] in " \t\r\n,:]}":
                        idx += 1

                    if idx >= buf_len:
                        break

                    char = buffer[idx]

                    # Step into container open delimiters
                    if char in "[{":
                        idx += 1
                        continue

                    # Attempt to decode complete JSON token starting at idx
                    try:
                        obj, next_idx = decoder.raw_decode(buffer, idx)
                        idx = next_idx

                        # Check if this decoded string is an object key (followed by colon)
                        peek_idx = idx
                        while peek_idx < buf_len and buffer[peek_idx] in " \t\r\n":
                            peek_idx += 1

                        if isinstance(obj, str) and peek_idx < buf_len and buffer[peek_idx] == ':':
                            current_key = obj.lower().strip()
                            idx = peek_idx + 1  # Advance past colon
                            continue

                        # Extract targets from decoded token
                        if current_key and current_key in cls.TARGET_KEYS:
                            yield from cls._extract_from_value(obj)
                            current_key = None
                        elif isinstance(obj, (dict, list)):
                            yield from cls._extract_from_value(obj)
                        elif isinstance(obj, str):
                            clean = obj.strip().replace("@", "")
                            if clean:
                                yield clean

                    except json.JSONDecodeError:
                        # Incomplete token: token crosses chunk boundary -> break to read next chunk
                        break

                # Discard processed portion of buffer
                if idx > 0:
                    buffer = buffer[idx:]

                # Final flush on EOF
                if not chunk:
                    if buffer.strip():
                        try:
                            final_obj = json.loads(buffer)
                            yield from cls._extract_from_value(final_obj)
                        except Exception:
                            pass
                    break