"""离线拼音输入法：jieba 词频 + pypinyin 编译出的 ime.db，本地 DP 组句。

不联网、不耗 token。给 CardputerZero 的 DeepSeek 客户端用，也可单独测试：
    python3 ime.py "jintiantianqi"
"""

from __future__ import annotations

import math
import re
import sqlite3
import sys

DEFAULT_DB = "/opt/dsh-chat/ime.db"
MAX_KEY = 12          # 单个词最多 12 个字母（4 个汉字）
PER_KEY = 10
WORD_PENALTY = -3.0   # 每多切一个词扣分，偏向长词


class LocalIME:
    def __init__(self, path: str = DEFAULT_DB):
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.cache: dict[str, list[tuple[str, int]]] = {}
        total = self.con.execute("SELECT SUM(freq) FROM words").fetchone()[0] or 1
        self.log_total = math.log(total)

    def lookup(self, py: str) -> list[tuple[str, int]]:
        hit = self.cache.get(py)
        if hit is not None:
            return hit
        rows = self.con.execute(
            "SELECT word, freq FROM words WHERE py=? ORDER BY freq DESC LIMIT ?",
            (py, PER_KEY)).fetchall()
        self.cache[py] = rows
        return rows

    def has_key(self, py: str) -> bool:
        return bool(self.lookup(py))

    def _char_fallback(self, s: str) -> list[str]:
        """整句切不出词时，按音节逐字取最常用字。"""
        out, i = [], 0
        while i < len(s):
            for size in (6, 5, 4, 3, 2, 1):
                piece = s[i:i + size]
                rows = self.lookup(piece)
                singles = [w for w, _ in rows if len(w) == 1]
                if singles:
                    out.append(singles[0])
                    i += size
                    break
            else:
                i += 1
        return ["".join(out)] if out else []

    def candidates(self, pinyin: str, k: int = 3) -> list[str]:
        s = re.sub(r"[^a-z]", "", pinyin.lower())
        n = len(s)
        if not n:
            return []

        # 用 log P(词) = log(freq) - log(总词频)，越碎分越低，长词才可能胜出
        # best[i] = 到第 i 个字母为止的 k 条最优 (score, text)
        best: list[list[tuple[float, str]]] = [[] for _ in range(n + 1)]
        best[0] = [(0.0, "")]
        for i in range(1, n + 1):
            pool: list[tuple[float, str]] = []
            for j in range(max(0, i - MAX_KEY), i):
                if not best[j]:
                    continue
                rows = self.lookup(s[j:i])
                if not rows:
                    continue
                for score0, text0 in best[j]:
                    for word, freq in rows:
                        pool.append((score0 + math.log(freq) - self.log_total,
                                     text0 + word))
            if pool:
                pool.sort(key=lambda x: -x[0])
                seen, keep = set(), []
                for score, text in pool:
                    if text in seen:
                        continue
                    seen.add(text)
                    keep.append((score, text))
                    if len(keep) >= k:
                        break
                best[i] = keep
        result = [text for _, text in best[n]]
        if not result:
            result = self._char_fallback(s)
        return result[:k]


def _main() -> int:
    db = DEFAULT_DB
    args = sys.argv[1:]
    if "--db" in args:
        i = args.index("--db")
        db = args[i + 1]
        del args[i:i + 2]
    ime = LocalIME(db)
    for text in args:
        print(f"{text} -> {ime.candidates(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
