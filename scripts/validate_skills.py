#!/usr/bin/env python3
"""Repo-level Agent Skills contract validator (checks A1-A9).

Validates every skill under skills/ against the Agent Skills open-standard
format contract and repository conventions:

A1  expected rds-supabase skills present, no unexpected skills (skills may be
    grouped in subdirectories — discovery is recursive; pre-existing foreign
    skills are tolerated but exempt from the contract checks)
A2  frontmatter fields: allowed set (incl. top-level version/tags), name rules,
    description length (1-1024), required top-level semver version, no drift
    between top-level version and metadata.version, tags limited to 5 strings
A3  SKILL.md body under 500 lines
A4  no INSTALLATION_GUIDE.md / QUICK_REFERENCE.md inside skills (README.md is
    allowed)
A5  reference file prefixes match references/_sections.md sections
A6  top-level version appears in the root CHANGELOG.md (version-drift tripwire)
A7  description carries a trigger signal and is at least 80 characters
A8  skill package file count within limit (40; explicit deviations registered
    in FILE_LIMIT_DEVIATIONS)
A9  every file in the skill package carries a whitelisted extension

File-level checks (A8/A9) only ever scan actual files under skills/ —
skills/huaweicloud-supabase/** and skills/huaweicloud-mcp-dev/** are the scan
roots; fixture-generated temporary directories elsewhere are never scanned.
Foreign skills stay exempt from A2-A9.

Complements the per-skill validator
(skills/huaweicloud-supabase/rds-supabase-mcp/scripts/validate-skill.py).
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
EXPECTED_SKILLS = {
    "rds-supabase-mcp",
    "rds-supabase-usage",
    "rds-supabase-postgres-best-practices",
    "rds-supabase-frontend",
    "rds-supabase-web-build",
    "rds-supabase-function-graph",
}
# Skills present in this repository that are not authored against the A1-A9
# contract (tolerated; A2-A9 skipped).
FOREIGN_SKILLS = {"huaweicloud-mcp-dev", "rds-supabase-mgr-mcp"}

ALLOWED_FIELDS = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
    "version",
    "tags",
}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
SECTION_RE = re.compile(r"^## \d+\. .+\((\w+)\)\s*$", re.MULTILINE)
TRIGGER_MARKERS = ("use when", "load this skill", "triggers:", "触发", "之前加载", "何时")
FORBIDDEN_FILES = {"INSTALLATION_GUIDE.md", "QUICK_REFERENCE.md"}
# Repo-wide wording standard: jargon that must never appear in any skill text.
# Rendered prose belongs to the user - use plain, formal Chinese instead
# (资源记录 / 执行记录 / 提示 / 写入·保存 / 添加标签 / 启动 / 强行重试·强行删除 / 彻底收尾).
BANNED_TERMS = ("台账", "账本", "话术", "落盘", "打标", "拉起", "硬试", "硬删", "干净收尾")

# Per-package file-count ceiling (spec 3.1). Explicit, reasoned deviations are
# registered per skill instead of weakening the global limit.
FILE_LIMIT_DEFAULT = 40
FILE_LIMIT_DEVIATIONS = {
    "rds-supabase-postgres-best-practices": {
        "limit": 45,
        "reason": "38 个规则文件是症状路由功能本体（渐进式披露正向实践），合并将破坏能力——记录为对规范 3.1 的显式偏离",
    }
}

# Extension whitelist for skill package payloads (spec 3.1): every file in a
# checked package — subdirectories included — must carry one of these.
EXTENSION_WHITELIST = {
    "md", "mdx", "txt", "html", "xml", "csv", "tsv", "json", "json5",
    "yaml", "yml", "toml", "ini", "cfg", "conf", "env", "properties", "dat",
    "sh", "ps1", "psm1", "psd1", "py", "js", "cjs", "mjs", "ts", "tsx", "jsx",
    "css", "scss", "sass", "svg", "r", "rb", "go", "rs", "swift", "kt",
    "java", "cs", "cpp", "c", "h", "hpp", "sql",
}
TAGS_LIMIT = 5


def parse_frontmatter(text: str) -> dict:
    """Parse the YAML frontmatter; falls back to a two-level regex parser."""
    if not text.startswith("---\n"):
        return {}
    block = text.split("---\n", 2)[1]
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(block)
        return data if isinstance(data, dict) else {}
    except ImportError:
        fm: dict = {}
        parent = None
        for line in block.splitlines():
            if not line.strip() or line.strip().startswith("#"):
                continue
            if line.startswith("  ") and parent:
                m = re.match(r"^\s+([a-zA-Z-]+):\s*['\"]?([^'\"\n]*)['\"]?\s*$", line)
                if m and isinstance(fm.get(parent), dict):
                    fm[parent][m.group(1)] = m.group(2)
            elif ":" in line and not line.startswith((" ", "\t", "-")):
                key, value = line.split(":", 1)
                key, value = key.strip(), value.strip()
                if value == "":
                    fm[key] = {}
                    parent = key
                else:
                    fm[key] = value.strip("'\"")
                    parent = None
        return fm


def tags_ok(value: object) -> bool:
    """True when a tags value is absent or a list of at most TAGS_LIMIT strings.

    Flow-style strings ("[a, b, c]") are accepted as well so the no-PyYAML
    fallback parser stays consistent with the PyYAML path.
    """
    if value is None:
        return True
    if isinstance(value, list):
        items: list[object] = value
    elif isinstance(value, str):
        s = value.strip()
        if not (s.startswith("[") and s.endswith("]")):
            return False
        items = [p.strip().strip("'\"") for p in s[1:-1].split(",") if p.strip()]
    else:
        return False
    return len(items) <= TAGS_LIMIT and all(isinstance(t, str) for t in items)


def main() -> int:
    errors: list[str] = []
    if not SKILLS_DIR.is_dir():
        print(f"FAIL: {SKILLS_DIR} not found")
        return 1

    # Skills may be grouped in subdirectories (e.g. skills/huaweicloud-supabase/);
    # discovery is recursive, skill identity is the SKILL.md parent directory name.
    found = {skill_md.parent.name for skill_md in SKILLS_DIR.rglob("SKILL.md")}
    missing = EXPECTED_SKILLS - found
    unknown = found - EXPECTED_SKILLS - FOREIGN_SKILLS
    if missing or unknown:
        errors.append(
            f"A1 skill set mismatch: missing {sorted(missing)}, unexpected {sorted(unknown)}"
        )

    changelog = REPO_ROOT / "CHANGELOG.md"
    changelog_text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""

    # Wording standard applies to every skill's rendered text (markdown only;
    # lint scripts and test fixtures are code and carry the terms deliberately).
    for md in sorted(SKILLS_DIR.rglob("*.md")):
        body = md.read_text(encoding="utf-8")
        for term in BANNED_TERMS:
            if term in body:
                errors.append(f"{md.relative_to(REPO_ROOT)}: banned jargon term {term!r}")

    for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        skill = skill_dir.name
        if skill not in EXPECTED_SKILLS:
            continue
        text = skill_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if not fm:
            errors.append(f"{skill}: A2 frontmatter missing or unparseable")
            continue

        extra = set(fm) - ALLOWED_FIELDS
        if extra:
            errors.append(f"{skill}: A2 unexpected frontmatter fields {sorted(extra)}")

        name = fm.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{skill}: A2 name missing")
        else:
            normalized = unicodedata.normalize("NFKC", name)
            if not (1 <= len(normalized) <= 64) or not NAME_RE.match(normalized):
                errors.append(f"{skill}: A2 invalid name {name!r}")
            if name != skill_dir.name:
                errors.append(f"{skill}: A2 name {name!r} != directory {skill_dir.name!r}")

        desc = fm.get("description")
        if not isinstance(desc, str) or not (1 <= len(desc) <= 1024):
            errors.append(f"{skill}: A2 description must be 1-1024 characters")
        elif len(desc) < 80 or not any(m in desc.lower() for m in TRIGGER_MARKERS):
            errors.append(f"{skill}: A7 description lacks trigger signal or is too short")

        meta = fm.get("metadata")
        meta = meta if isinstance(meta, dict) else {}

        # Top-level version is the required baseline; metadata.version, when
        # kept alongside, must stay in lockstep with it (drift tripwire).
        top_version = fm.get("version")
        if not isinstance(top_version, str) or not SEMVER_RE.match(top_version):
            errors.append(
                f'{skill}: A2 top-level version missing (required, e.g. "2.15.0")'
            )
        else:
            if changelog_text and top_version not in changelog_text:
                errors.append(
                    f"{skill}: A6 version {top_version} not found in root CHANGELOG.md"
                )
            meta_version = meta.get("version")
            if isinstance(meta_version, str) and meta_version != top_version:
                errors.append(
                    f"{skill}: version drift between top-level and metadata.version"
                )

        meta_version = meta.get("version")
        if not isinstance(meta_version, str) or not SEMVER_RE.match(meta_version):
            errors.append(f"{skill}: A2 metadata.version must be a semver string")

        if not tags_ok(fm.get("tags")):
            errors.append(f"{skill}: tags must be a list of at most 5 strings")
        if not tags_ok(meta.get("tags")):
            errors.append(f"{skill}: metadata.tags must be a list of at most 5 strings")

        body = text.split("---\n", 2)[2] if text.startswith("---\n") else text
        if body.count("\n") >= 500:
            errors.append(f"{skill}: A3 body has {body.count(chr(10))} lines (limit: 500)")

        package_files = sorted(f for f in skill_dir.rglob("*") if f.is_file())
        for f in package_files:
            if f.name in FORBIDDEN_FILES:
                errors.append(f"{skill}: A4 forbidden file {f.relative_to(skill_dir)}")

        limit = FILE_LIMIT_DEVIATIONS.get(skill, {}).get("limit", FILE_LIMIT_DEFAULT)
        if len(package_files) > limit:
            errors.append(f"{skill}: A8 file count {len(package_files)} exceeds limit {limit}")

        for f in package_files:
            ext = f.suffix.lstrip(".").lower()
            if ext not in EXTENSION_WHITELIST:
                errors.append(
                    f"{skill}: non-whitelisted extension: {f.relative_to(skill_dir)}"
                )

        refs_dir = skill_dir / "references"
        sections_file = refs_dir / "_sections.md"
        if sections_file.is_file() and refs_dir.is_dir():
            prefixes = set(SECTION_RE.findall(sections_file.read_text(encoding="utf-8")))
            for ref in refs_dir.glob("*.md"):
                if ref.name.startswith("_"):
                    continue
                if ref.name.split("-", 1)[0] not in prefixes:
                    errors.append(
                        f"{skill}: A5 reference {ref.name!r} prefix not in _sections.md"
                    )

    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        return 1
    print(f"validate-skills: OK ({len(found)} skills)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
