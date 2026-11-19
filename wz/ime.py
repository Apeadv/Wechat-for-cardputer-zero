"""Offline pinyin IME.

The dictionary is the 77k-entry SQLite DB built from jieba word frequencies +
pypinyin (see tools/build_ime_db.py in the repo).  Conversion is a small DP over
the pinyin string that favours long, frequent words -- no network, no tokens,
works on the 4x A53 CPU in a few milliseconds.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3

MAX_KEY = 12          # longest pinyin key (4 hanzi)
PER_KEY = 10          # candidates fetched per split
WORD_PENALTY = -3.0   # unused in the log-prob model, kept for tuning

CJK_RE = re.compile(r"[\u3400-\u9fff]")

SYLLABLES = set("""
a ai an ang ao ba bai ban bang bao bei ben beng bi bian biao bie bin bing bo bu
ca cai can cang cao ce cen ceng cha chai chan chang chao che chen cheng chi chong
chou chu chua chuai chuan chuang chui chun chuo ci cong cou cu cuan cui cun cuo
da dai dan dang dao de dei den deng di dia dian diao die ding diu dong dou du duan
dui dun duo e ei en eng er fa fan fang fei fen feng fo fou fu ga gai gan gang gao
ge gei gen geng gong gou gu gua guai guan guang gui gun guo ha hai han hang hao he
hei hen heng hong hou hu hua huai huan huang hui hun huo ji jia jian jiang jiao jie
jin jing jiong jiu ju juan jue jun ka kai kan kang kao ke kei ken keng kong kou ku
kua kuai kuan kuang kui kun kuo la lai lan lang lao le lei leng li lia lian liang
liao lie lin ling liu long lou lu luan lue lun luo lv lve ma mai man mang mao me
mei men meng mi mian miao mie min ming miu mo mou mu na nai nan nang nao ne nei nen
neng ni nian niang niao nie nin ning niu nong nou nu nuan nue nuo nv nve o ou pa
pai pan pang pao pei pen peng pi pian piao pie pin ping po pou pu qi qia qian qiang
qiao qie qin qing qiong qiu qu quan que qun ran rang rao re ren reng ri rong rou ru
ruan rui run ruo sa sai san sang sao se sen seng sha shai shan shang shao she shei
shen sheng shi shou shu shua shuai shuan shuang shui shun shuo si song sou su suan
sui sun suo ta tai tan tang tao te teng ti tian tiao tie ting tong tou tu tuan tui
tun tuo wa wai wan wang wei wen weng wo wu xi xia xian xiang xiao xie xin xing
xiong xiu xu xuan xue xun ya yan yang yao ye yi yin ying yo yong you yu yuan yue
yun za zai zan zang zao ze zei zen zeng zha zhai zhan zhang zhao zhe zhen zheng
zhi zhong zhou zhu zhua zhuai zhuan zhuang zhui zhun zhuo zi zong zou zu zuan zui
zun zuo
""".split())


def split_pinyin(text: str):
    out, i, n = [], 0, len(text)
    while i < n:
        for size in (6, 5, 4, 3, 2, 1):
            piece = text[i:i + size]
            if piece in SYLLABLES:
                out.append(piece)
                i += size
                break
        else:
            return None
    return out


def looks_like_pinyin(text: str) -> bool:
    if len(text) < 4 or not text.isascii() or not text.isalpha():
        return False
    parts = split_pinyin(text.lower())
    return bool(parts) and len(parts) >= 2


def is_single_syllable(text: str) -> bool:
    return 1 <= len(text) <= 6 and text.isalpha() and text.lower() in SYLLABLES


class LocalIME:
    def __init__(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        self.path = path
        self.con = sqlite3.connect("file:%s?mode=ro" % path, uri=True,
                                   check_same_thread=False)
        self.cache: dict[str, list] = {}
        total = self.con.execute("SELECT SUM(freq) FROM words").fetchone()[0] or 1
        self.log_total = math.log(total)

    def lookup(self, py: str) -> list:
        hit = self.cache.get(py)
        if hit is not None:
            return hit
        rows = self.con.execute(
            "SELECT word, freq FROM words WHERE py=? ORDER BY freq DESC LIMIT ?",
            (py, PER_KEY)).fetchall()
        if len(self.cache) > 4000:
            self.cache.clear()
        self.cache[py] = rows
        return rows

    def has_key(self, py: str) -> bool:
        return bool(self.lookup(py))

    def _char_fallback(self, s: str) -> list:
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

    def candidates(self, pinyin: str, k: int = 9) -> list:
        s = re.sub(r"[^a-z]", "", pinyin.lower())
        n = len(s)
        if not n:
            return []

        best = [[] for _ in range(n + 1)]
        best[0] = [(0.0, "")]
        for i in range(1, n + 1):
            pool = []
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
                    if len(keep) >= max(k, 3):
                        break
                best[i] = keep
        result = [text for _, text in best[n]]
        if not result:
            result = self._char_fallback(s)
        return result[:k]


def load(path: str):
    try:
        return LocalIME(path)
    except Exception:
        return None
