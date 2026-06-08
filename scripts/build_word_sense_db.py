"""
build_word_sense_db.py — 从 ECDICT 构建 WordSenseDB.json

数据源：ECDICT (skywind3000/ECDICT)
筛选标签：cet4, cet6, ky(考研), ielts, toefl, gk(高考)
排序：Collins 频率 → BNC 频率 → frq 频率
目标规模：~10,000 词条，含中文释义与多义词检测
"""

import json
import re
import sqlite3
import urllib.request
import zipfile
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = PROJECT_ROOT / ".cache"

ECDICT_ZIP_URL = "https://github.com/skywind3000/ECDICT/releases/download/1.0.28/ecdict-sqlite-28.zip"
ECDICT_ZIP_PATH = CACHE_DIR / "ecdict-sqlite-28.zip"
ECDICT_DB_PATH = CACHE_DIR / "ecdict.db"

OUTPUT_PATH = DATA_DIR / "WordSenseDB.json"

TARGET_TAGS = ("cet4", "cet6", "ky", "ielts", "toefl", "gk",'zk','')
MAX_WORDS = 10000

# 非标准词过滤：含引号/空格/点号/短横的词
INVALID_PATTERN = re.compile(r"[' .\-]")


# ── 下载 ──────────────────────────────────────────────────


def download_ecdict():
    if ECDICT_DB_PATH.exists():
        print(f"[跳过] {ECDICT_DB_PATH} 已存在")
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not ECDICT_ZIP_PATH.exists():
        print(f"下载 {ECDICT_ZIP_URL} ...")
        urllib.request.urlretrieve(ECDICT_ZIP_URL, ECDICT_ZIP_PATH)
        print("下载完成")

    print("解压中...")
    with zipfile.ZipFile(ECDICT_ZIP_PATH, "r") as zf:
        db_member = next((m for m in zf.namelist() if m.endswith(".db")), None)
        if db_member is None:
            zf.extractall(CACHE_DIR)
        else:
            zf.extract(db_member, CACHE_DIR)
            extracted = CACHE_DIR / db_member
            if extracted != ECDICT_DB_PATH:
                extracted.rename(ECDICT_DB_PATH)

    for item in list(CACHE_DIR.iterdir()):
        if item.is_dir():
            for f in item.iterdir():
                f.rename(CACHE_DIR / f.name)
            item.rmdir()

    print(f"解压完成 → {ECDICT_DB_PATH}")


# ── 释义解析 ──────────────────────────────────────────────


def clean_translation(raw: str) -> str:
    """去除 POS 标签，返回纯释义文本"""
    if not raw:
        return ""
    # 去掉首部词性标记如 "n. ", "vt. ", "a. ", "pl. " 等
    raw = re.sub(r"^[a-z]+\.\s*", "", raw.strip())
    return raw.strip()


def split_senses(raw: str) -> list[str]:
    """将 ECDICT translation 字段拆分为独立义项"""
    if not raw:
        return []
    parts = re.split(r"[\n\r]+", raw)
    senses = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        for s in re.split(r"[；;]", p):
            s = clean_translation(s)
            if s and len(s) >= 1:
                senses.append(s)
    seen = set()
    unique = []
    for s in senses:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def make_sense_id(word: str, index: int) -> str:
    return f"{word}_{index + 1}"


def is_valid_word(word: str) -> bool:
    """过滤非标准词条（含引号、空格、点号、短横）"""
    return not INVALID_PATTERN.search(word)


# ── 构建 ──────────────────────────────────────────────────


def build():
    conn = sqlite3.connect(str(ECDICT_DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 构造 WHERE 条件：AND 连接所有 LIKE
    tag_conditions = " OR ".join(f"tag LIKE '%{t}%'" for t in TARGET_TAGS)
    query = f"""
        SELECT word, translation, collins, bnc, frq
        FROM stardict
        WHERE ({tag_conditions})
          AND translation IS NOT NULL
          AND translation != ''
        ORDER BY collins ASC NULLS LAST,
                 bnc ASC NULLS LAST,
                 frq DESC NULLS LAST
    """
    cursor.execute(query)

    entries: dict[str, list[str]] = {}
    seen = set()

    for row in cursor:
        word = row["word"].strip().lower()
        if word in seen:
            continue
        if not is_valid_word(word):
            continue

        senses = split_senses(row["translation"])
        if not senses:
            continue

        seen.add(word)
        entries[word] = senses

    conn.close()

    # 构建 WordSenseDB 结构
    output: dict = {}
    for word, meanings in entries.items():
        senses = []
        for i, meaning in enumerate(meanings):
            senses.append({"id": make_sense_id(word, i), "meaning": meaning})
        output[word] = {
            "is_polysemous": len(senses) > 1,
            "senses": senses,
        }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    poly_count = sum(1 for e in output.values() if e["is_polysemous"])
    total_senses = sum(len(e["senses"]) for e in output.values())
    print(f"\n写入 {OUTPUT_PATH}")
    print(f"总词数: {len(output)}")
    print(f"多义词: {poly_count}")
    print(f"单义词: {len(output) - poly_count}")
    print(f"总义项: {total_senses}")


if __name__ == "__main__":
    download_ecdict()
    build()
