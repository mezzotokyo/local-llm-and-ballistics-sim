#!/usr/bin/env python3
"""Detect stray characters in the repository's text files.

The tool was added after several Japanese sentences picked up characters from
other writing systems while being generated. Korean, Arabic, Cyrillic,
Indic, and Southeast Asian scripts are never intentional in this repository,
and the simplified-Chinese forms listed below never occur in correct Japanese.

A whole Chinese word can also slip in when every character it uses is shared
with Japanese (for example ``本地``, whose characters are ordinary Japanese
kanji), so a curated list of Chinese-only words is checked as well.

Findings are reported as ``path:line: column`` and the exit status is ``1``
when anything is found, so the script can be wired into a pre-commit hook.

Usage::

    python3 tools/check_text_hygiene.py                # whole repository
    python3 tools/check_text_hygiene.py range_calculator/HISTORY.md
    python3 tools/check_text_hygiene.py --list-rules   # show the rule sets

On Windows, ``python`` may be used in place of ``python3`` when the
``python3`` alias is unavailable (for example, a python.org installation
without the Python Install Manager).
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------
# Rule set 1: whole scripts that never belong in this repository
# --------------------------------------------------------------------------

SCRIPT_RANGES: tuple[tuple[str, int, int], ...] = (
    ('Hangul Jamo', 0x1100, 0x11FF),
    ('Hangul Compat Jamo', 0x3130, 0x318F),
    ('Hangul Jamo Ext-A', 0xA960, 0xA97F),
    ('Hangul Syllables', 0xAC00, 0xD7A3),
    ('Hangul Jamo Ext-B', 0xD7B0, 0xD7FF),
    ('Arabic', 0x0600, 0x06FF),
    ('Arabic Supplement', 0x0750, 0x077F),
    ('Arabic Extended-A', 0x08A0, 0x08FF),
    ('Syriac', 0x0700, 0x074F),
    ('Thaana', 0x0780, 0x07BF),
    ('NKo', 0x07C0, 0x07FF),
    ('Hebrew', 0x0590, 0x05FF),
    ('Cyrillic', 0x0400, 0x04FF),
    ('Cyrillic Supplement', 0x0500, 0x052F),
    ('Devanagari', 0x0900, 0x097F),
    ('Bengali', 0x0980, 0x09FF),
    ('Gurmukhi', 0x0A00, 0x0A7F),
    ('Gujarati', 0x0A80, 0x0AFF),
    ('Tamil', 0x0B80, 0x0BFF),
    ('Telugu', 0x0C00, 0x0C7F),
    ('Kannada', 0x0C80, 0x0CFF),
    ('Malayalam', 0x0D00, 0x0D7F),
    ('Sinhala', 0x0D80, 0x0DFF),
    ('Thai', 0x0E00, 0x0E7F),
    ('Lao', 0x0E80, 0x0EFF),
    ('Tibetan', 0x0F00, 0x0FFF),
    ('Myanmar', 0x1000, 0x109F),
    ('Georgian', 0x10A0, 0x10FF),
    ('Ethiopic', 0x1200, 0x137F),
    ('Cherokee', 0x13A0, 0x13FF),
    ('Khmer', 0x1780, 0x17FF),
    ('Mongolian', 0x1800, 0x18AF),
    ('Glagolitic', 0x2C00, 0x2C7F),
    ('Coptic', 0x2C80, 0x2CFF),
    ('Tifinagh', 0x2D30, 0x2D7F),
    ('Latin Extended Additional', 0x1E00, 0x1EFF),
    ('Vai', 0xA500, 0xA63F),
    ('Bamum', 0xA6A0, 0xA6FF),
    ('Javanese', 0xA980, 0xA9DF),
    ('Cham', 0xAA00, 0xAA5F),
    ('Meetei Mayek', 0xABC0, 0xABFF),
)

# Ranges that are used on purpose and must not be reported.
ALLOWED_RANGES: tuple[tuple[str, int, int], ...] = (
    ('Greek and Coptic', 0x0370, 0x03FF),  # theta appears in the physics docs
    ('General Punctuation', 0x2000, 0x206F),
    ('Superscripts and Subscripts', 0x2070, 0x209F),
    ('Currency Symbols', 0x20A0, 0x20CF),
    ('Combining Diacritics', 0x0300, 0x036F),
    ('Letterlike Symbols', 0x2100, 0x214F),
    ('Number Forms', 0x2150, 0x218F),
    ('Arrows', 0x2190, 0x21FF),
    ('Mathematical Operators', 0x2200, 0x22FF),
    ('Box Drawing', 0x2500, 0x257F),
    ('Block Elements', 0x2580, 0x259F),
    ('Geometric Shapes', 0x25A0, 0x25FF),
    ('CJK Symbols and Punctuation', 0x3000, 0x303F),
    ('Hiragana', 0x3040, 0x309F),
    ('Katakana', 0x30A0, 0x30FF),
    ('Halfwidth Forms', 0xFF61, 0xFF9F),
    ('Fullwidth Forms', 0xFFA0, 0xFF60),
)

# --------------------------------------------------------------------------
# Rule set 2: simplified-Chinese-only ideographs
#
# Every entry below was verified to have a different code point from the
# Japanese shinjitai character it simplified, so none of them can appear in
# correct Japanese. Characters shared with Japanese (for example U+65AD) are
# deliberately absent because flagging them would produce false positives.
# --------------------------------------------------------------------------

SIMPLIFIED_ONLY = (
    '严义书买产优决单卖压发变听处复实对应异录择换敛时杂权构样检测环现确类结继艺节药营则'
    '蓝虑补袭计认讨让议记论设证识试误说请读调谈谢负财责败货质购贿资赏赛转轮输边达过运'
    '还进远违连适选遗邮释针钟钢钱铁错镇镜长门闭问间阳阴际陆陈险隐难雾顶项顺预领频题风'
    '飞饭饮马驾验骑鱼鲁鲜鸟鸡齐齿龙获锁规弹'
)

# --------------------------------------------------------------------------
# Rule set 3: Chinese-only words built entirely from characters shared with
# Japanese.
#
# The simplified-Chinese rule above cannot catch a word such as ``本地`` when
# every character in it is also an ordinary Japanese kanji. The entries below
# were each verified to be natural Chinese but not valid Japanese, so they can
# only be contamination. Words that are also valid Japanese (for example
# ``使用``, ``提供``, ``保存``, ``更新``, ``配置``) are deliberately absent to
# avoid false positives, as are words already covered by the character rule.
# --------------------------------------------------------------------------

CHINESE_WORDS = (
    '本地', '文件', '程序', '数据', '默认', '信息', '硬件', '参数', '函数',
    '字符串', '路径', '地址', '功能', '部署', '添加', '返回', '等待', '安装',
    '由于', '如果', '但是', '然后', '我们', '你们', '网络', '软件', '系统',
    '服务', '用户', '状态', '加载', '下载', '上传', '卸载', '删除', '影响',
    '关于', '因为',
)

SKIP_DIRECTORIES = frozenset(
    {'.git', '__pycache__', '.mypy_cache', '.pytest_cache', 'node_modules', 'dist'}
)
SKIP_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.pyc'})
TEXT_SUFFIXES = frozenset(
    {
        '.py', '.md', '.json', '.csv', '.txt', '.toml', '.cfg', '.ini',
        '.yaml', '.yml', '.sh', '.swift',
    }
)
EXTRA_FILENAMES = frozenset({'.gitignore', 'pre-commit'})


def _in_any(char: str, ranges: tuple[tuple[str, int, int], ...]) -> str | None:
    point = ord(char)
    for name, low, high in ranges:
        if low <= point <= high:
            return name
    return None


def classify(char: str) -> str | None:
    """Return a description of why ``char`` is suspicious, or ``None`` if it is fine."""
    point = ord(char)
    if point < 0x80:
        return None
    if _in_any(char, ALLOWED_RANGES):
        return None
    if 0x3400 <= point <= 0x4DBF:  # CJK Extension A: rare kanji, used as-is
        return None
    if 0x4E00 <= point <= 0x9FFF:  # CJK Unified Ideographs
        if char in SIMPLIFIED_ONLY:
            return 'simplified-Chinese form'
        return None
    if 0xF900 <= point <= 0xFAFF:  # CJK Compatibility Ideographs
        return None
    name = _in_any(char, SCRIPT_RANGES)
    if name is not None:
        return f'{name} script'
    return None


def _in_nested_repo(path: Path, root: Path) -> bool:
    """Return True when ``path`` lies inside a repository nested under ``root``.

    A nested checkout carries its own copy of this tool's rule literals, so
    scanning it would report false positives that are not part of ``root``.
    """
    current = path.parent
    while current != root and current != current.parent:
        if (current / '.git').exists():
            return True
        current = current.parent
    return False


def iter_files(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if root.is_file():
            found.append(root)
            continue
        for path in sorted(root.rglob('*')):
            if not path.is_file():
                continue
            if SKIP_DIRECTORIES & set(path.parts):
                continue
            if _in_nested_repo(path, root):
                continue
            if path.suffix in SKIP_SUFFIXES:
                continue
            if path.suffix not in TEXT_SUFFIXES and path.name not in EXTRA_FILENAMES:
                continue
            found.append(path)
    return found


def find_chinese_words(line: str) -> list[tuple[str, int]]:
    """Return ``(word, column)`` for each Chinese-only word found in ``line``."""
    matches: list[tuple[str, int]] = []
    for word in CHINESE_WORDS:
        start = 0
        while True:
            index = line.find(word, start)
            if index < 0:
                break
            matches.append((word, index + 1))
            start = index + len(word)
    return sorted(matches, key=lambda item: item[1])


def scan(path: Path) -> list[tuple[int, int, str, str, str]]:
    """Return ``(line, column, char, reason, line_text)`` for each finding."""
    try:
        text = path.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        return []

    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for column, char in enumerate(line, 1):
            reason = classify(char)
            if reason is not None:
                findings.append((number, column, char, reason, line.strip()))
        for word, column in find_chinese_words(line):
            findings.append((number, column, word, 'Chinese-only word', line.strip()))
    return findings


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('paths', nargs='*', default=['.'], help='files or directories')
    parser.add_argument(
        '--list-rules', action='store_true', help='print the rule sets and exit'
    )
    args = parser.parse_args(argv)

    if args.list_rules:
        print('Rejected script ranges:')
        for name, low, high in SCRIPT_RANGES:
            print(f'  U+{low:04X}-U+{high:04X}  {name}')
        print(f'\nSimplified-Chinese-only characters ({len(SIMPLIFIED_ONLY)}):')
        print('  ' + SIMPLIFIED_ONLY)
        print(f'\nChinese-only words ({len(CHINESE_WORDS)}):')
        print('  ' + ' '.join(CHINESE_WORDS))
        return 0

    roots = [Path(item) for item in (args.paths or ['.'])]
    # This file carries the patterns verbatim, so scanning it would report them.
    roots = [r for r in roots if Path(__file__).resolve() not in r.resolve().parents
             and r.resolve() != Path(__file__).resolve().parent]

    total = 0
    scanned = 0
    for path in iter_files(roots):
        if path.resolve() == Path(__file__).resolve():
            continue
        scanned += 1
        for number, column, char, reason, context in scan(path):
            total += 1
            if len(char) == 1:
                codepoint = f'U+{ord(char):04X}'
                name = unicodedata.name(char, 'unnamed')
                print(f'{path}:{number}:{column}: {reason}: {char!r} {codepoint} {name}')
            else:
                print(f'{path}:{number}:{column}: {reason}: {char!r}')
            print(f'    {context}')

    print(f'\nscanned {scanned} file(s), {total} finding(s)')
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
