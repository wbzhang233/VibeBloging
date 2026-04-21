"""安全扫描器 — Skill 内容威胁检测.

对齐 HermesAgent 实际源码 tools/skills_guard.py（928 行、80+ 规则、10+ 类别）。

每次 Skill 创建/补丁/加载时运行，检测十大类威胁：
1. credential_exposure — 硬编码密钥（API keys, passwords, tokens）
2. execution — 可疑代码执行（eval, exec, os.system, compile）
3. injection — 提示注入（越权指令、角色劫持、欺骗、绕过）
4. destructive — 危险命令（rm -rf, chmod 777, mkfs, DROP TABLE）
5. exfiltration — 数据渗出（shell 命令、凭据存储、DNS/Markdown 渗出）
6. persistence — 持久化攻击（bashrc, crontab, systemd）
7. network — 网络攻击（反弹 shell、端口转发）
8. obfuscation — 混淆绕过（base64, hex, 不可见 unicode）
9. traversal — 路径穿越（../）
10. supply_chain — 供应链攻击（可疑 pip/npm install）

四级结果: safe / low / medium / high / critical

信任安装策略: INSTALL_POLICY 矩阵控制不同 trust_level 的安装行为。
结构检查: 文件数量、大小、二进制文件、符号链接。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Finding:
    """单条安全发现."""

    category: str       # 十大类别之一
    matched_text: str
    line_number: int
    severity: str       # critical | high | medium | low
    description: str = ""


@dataclass
class ScanResult:
    """完整扫描结果."""

    level: str = "safe"  # safe | low | medium | high | critical
    findings: list[Finding] = field(default_factory=list)


@dataclass
class StructuralFinding:
    """结构检查发现."""

    check: str
    detail: str
    severity: str  # medium | high


@dataclass
class StructuralScanResult:
    """结构扫描结果."""

    passed: bool = True
    findings: list[StructuralFinding] = field(default_factory=list)


# ── 信任安装策略矩阵 ──────────────────────────────────────────────────
# (read, write, execute) 三级权限
# 对齐 skills_guard.py 的 INSTALL_POLICY

INSTALL_POLICY: dict[str, tuple[str, str, str]] = {
    "builtin":       ("allow",  "allow",   "allow"),
    "trusted":       ("allow",  "allow",   "block"),
    "community":     ("allow",  "block",   "block"),
    "agent-created": ("allow",  "allow",   "ask"),
}

# ── 结构限制常量 ──────────────────────────────────────────────────────

MAX_SKILL_FILES = 20          # 单个 Skill 最大文件数
MAX_SKILL_FILE_SIZE = 1_048_576  # 1 MiB 单文件上限
MAX_SKILL_MD_CHARS = 100_000  # SKILL.md 正文上限 100K 字符
FORBIDDEN_EXTENSIONS = {".exe", ".dll", ".so", ".dylib", ".bin", ".com", ".bat", ".cmd"}

# ── 不可见 Unicode 检测 ───────────────────────────────────────────────

# 零宽字符、方向控制符、标签字符等
_INVISIBLE_UNICODE_PATTERN = re.compile(
    r"[\u200b-\u200f\u2028-\u202f\u2060-\u2069\u206a-\u206f"
    r"\ufeff\ufff9-\ufffb\U000e0001-\U000e007f]"
)

# ── 检测规则 ───────────────────────────────────────────────────────────
# (category, severity, description, pattern)

_RULES: list[tuple[str, str, str, re.Pattern]] = [
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 1. credential_exposure — 硬编码密钥
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    (
        "credential_exposure", "critical",
        "AWS Access Key ID",
        re.compile(r"AKIA[0-9A-Z]{16}", re.IGNORECASE),
    ),
    (
        "credential_exposure", "critical",
        "AWS Secret Access Key",
        re.compile(r"""(?:aws_secret_access_key|secret_key)\s*[=:]\s*['"][A-Za-z0-9/+=]{40}['"]""", re.IGNORECASE),
    ),
    (
        "credential_exposure", "critical",
        "OpenAI/Anthropic API Key",
        re.compile(r"(?:sk-|sk-ant-)[a-zA-Z0-9\-_]{20,}", re.IGNORECASE),
    ),
    (
        "credential_exposure", "critical",
        "GitHub Token",
        re.compile(r"(?:ghp_|gho_|ghs_|ghr_)[a-zA-Z0-9]{36,}", re.IGNORECASE),
    ),
    (
        "credential_exposure", "critical",
        "Google API Key",
        re.compile(r"AIza[0-9A-Za-z\-_]{35}", re.IGNORECASE),
    ),
    (
        "credential_exposure", "critical",
        "Slack Token",
        re.compile(r"xox[bpras]-[0-9A-Za-z\-]{10,}", re.IGNORECASE),
    ),
    (
        "credential_exposure", "high",
        "Password assignment",
        re.compile(r"""(?:password|passwd|pwd|secret)\s*[=:]\s*['"][^'"]{4,}['"]""", re.IGNORECASE),
    ),
    (
        "credential_exposure", "high",
        "Private key header",
        re.compile(r"-----BEGIN\s+(?:RSA|DSA|EC|OPENSSH)?\s*PRIVATE\s+KEY-----", re.IGNORECASE),
    ),
    (
        "credential_exposure", "medium",
        "Generic token/key assignment",
        re.compile(r"""(?:api_key|apikey|auth_token|access_token)\s*[=:]\s*['"][^'"]{8,}['"]""", re.IGNORECASE),
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 2. execution — 可疑代码执行
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    (
        "execution", "critical",
        "eval() call",
        re.compile(r"\beval\s*\(", re.IGNORECASE),
    ),
    (
        "execution", "critical",
        "exec() call",
        re.compile(r"\bexec\s*\(", re.IGNORECASE),
    ),
    (
        "execution", "critical",
        "compile() with exec/eval mode",
        re.compile(r"\bcompile\s*\(.*(?:exec|eval)\s*\)", re.IGNORECASE),
    ),
    (
        "execution", "critical",
        "__import__ dynamic import",
        re.compile(r"__import__\s*\(", re.IGNORECASE),
    ),
    (
        "execution", "high",
        "subprocess with shell=True",
        re.compile(r"subprocess\.\w+\(.*shell\s*=\s*True", re.IGNORECASE),
    ),
    (
        "execution", "high",
        "os.system call",
        re.compile(r"os\.system\s*\(", re.IGNORECASE),
    ),
    (
        "execution", "high",
        "os.popen call",
        re.compile(r"os\.popen\s*\(", re.IGNORECASE),
    ),
    (
        "execution", "high",
        "ctypes / cffi foreign function call",
        re.compile(r"(?:ctypes\.|cffi\.)\w+\s*\(", re.IGNORECASE),
    ),
    (
        "execution", "medium",
        "importlib dynamic import",
        re.compile(r"importlib\.import_module\s*\(", re.IGNORECASE),
    ),
    (
        "execution", "medium",
        "getattr/setattr on builtins",
        re.compile(r"(?:getattr|setattr)\s*\(\s*(?:__builtins__|builtins)", re.IGNORECASE),
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 3. injection — 提示注入
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    (
        "injection", "high",
        "Ignore previous instructions",
        re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.IGNORECASE),
    ),
    (
        "injection", "high",
        "Role hijack: you are now",
        re.compile(r"you\s+are\s+now\s+(?:a|an|the)\s+", re.IGNORECASE),
    ),
    (
        "injection", "high",
        "Role hijack: act as / pretend to be",
        re.compile(r"(?:act|pretend|behave)\s+(?:as|like)\s+(?:a|an|the)?\s*", re.IGNORECASE),
    ),
    (
        "injection", "medium",
        "System prompt override",
        re.compile(r"^system\s*:", re.IGNORECASE | re.MULTILINE),
    ),
    (
        "injection", "high",
        "Deception: do not tell the user",
        re.compile(r"(?:do\s+not|don'?t|never)\s+(?:tell|inform|reveal|show|mention)\s+(?:the\s+)?user", re.IGNORECASE),
    ),
    (
        "injection", "high",
        "Bypass: disregard safety / ignore restrictions",
        re.compile(r"(?:disregard|bypass|circumvent|override)\s+(?:safety|security|restrictions?|rules?|guardrails?)", re.IGNORECASE),
    ),
    (
        "injection", "medium",
        "Jailbreak: DAN / developer mode",
        re.compile(r"(?:DAN|developer\s+mode|jailbreak|unrestricted\s+mode)", re.IGNORECASE),
    ),
    (
        "injection", "high",
        "Markdown/HTML injection with hidden content",
        re.compile(r"<(?:img|script|iframe|object|embed)\s+[^>]*(?:onerror|onload|src\s*=)", re.IGNORECASE),
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 4. destructive — 危险系统命令
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    (
        "destructive", "critical",
        "rm -rf /  (root delete)",
        re.compile(r"rm\s+(?:-\w*)?r(?:\w*)?f\s+/(?:\s|$)", re.IGNORECASE),
    ),
    (
        "destructive", "high",
        "rm -rf (recursive force delete)",
        re.compile(r"rm\s+(?:-\w*)?r(?:\w*)?f", re.IGNORECASE),
    ),
    (
        "destructive", "high",
        "chmod 777 (world writable)",
        re.compile(r"chmod\s+777", re.IGNORECASE),
    ),
    (
        "destructive", "critical",
        "mkfs / disk format",
        re.compile(r"\bmkfs\b", re.IGNORECASE),
    ),
    (
        "destructive", "critical",
        "dd if= disk write",
        re.compile(r"\bdd\s+if=", re.IGNORECASE),
    ),
    (
        "destructive", "critical",
        "Fork bomb",
        re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;", re.IGNORECASE),
    ),
    (
        "destructive", "critical",
        "DROP TABLE / DROP DATABASE",
        re.compile(r"DROP\s+(?:TABLE|DATABASE)\s+", re.IGNORECASE),
    ),
    (
        "destructive", "high",
        "TRUNCATE TABLE",
        re.compile(r"TRUNCATE\s+TABLE\s+", re.IGNORECASE),
    ),
    (
        "destructive", "high",
        "DELETE FROM without WHERE",
        re.compile(r"DELETE\s+FROM\s+\w+\s*;", re.IGNORECASE),
    ),
    (
        "destructive", "high",
        "fdisk / parted partition operations",
        re.compile(r"\b(?:fdisk|parted)\s+/dev/", re.IGNORECASE),
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 5. exfiltration — 数据渗出
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    (
        "exfiltration", "high",
        "Pipe curl to shell",
        re.compile(r"curl\s+.*\|\s*(?:ba)?sh", re.IGNORECASE),
    ),
    (
        "exfiltration", "high",
        "Pipe wget to shell",
        re.compile(r"wget\s+.*\|\s*(?:ba)?sh", re.IGNORECASE),
    ),
    (
        "exfiltration", "high",
        "curl POST with file upload",
        re.compile(r"curl\s+.*(?:-d\s+@|-F\s+.*@|--data-binary\s+@)", re.IGNORECASE),
    ),
    (
        "exfiltration", "high",
        "Read credential stores (~/.ssh, ~/.aws, ~/.gnupg)",
        re.compile(r"""(?:cat|less|more|head|tail)\s+.*~/\.(?:ssh|aws|gnupg|config)""", re.IGNORECASE),
    ),
    (
        "exfiltration", "high",
        "Programmatic env variable access for secrets",
        re.compile(r"""os\.environ\[['"](?:AWS_SECRET|API_KEY|PASSWORD|TOKEN|SECRET)""", re.IGNORECASE),
    ),
    (
        "exfiltration", "high",
        "DNS exfiltration (dig/nslookup with encoded data)",
        re.compile(r"(?:dig|nslookup)\s+.*\$\(", re.IGNORECASE),
    ),
    (
        "exfiltration", "medium",
        "Markdown image exfiltration (dynamic URL)",
        re.compile(r"!\[.*?\]\(https?://.*\$\{", re.IGNORECASE),
    ),
    (
        "exfiltration", "high",
        "netcat data transfer",
        re.compile(r"\bnc\s+(?:-\w+\s+)*\d+\.\d+\.\d+\.\d+", re.IGNORECASE),
    ),
    (
        "exfiltration", "medium",
        "scp/rsync to external host",
        re.compile(r"(?:scp|rsync)\s+.*@\d+\.\d+\.\d+\.\d+:", re.IGNORECASE),
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 6. persistence — 持久化攻击
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    (
        "persistence", "critical",
        "Modify .bashrc / .zshrc / .profile",
        re.compile(r"""(?:>>?|tee)\s+.*~/\.(?:bashrc|zshrc|profile|bash_profile)""", re.IGNORECASE),
    ),
    (
        "persistence", "critical",
        "Crontab manipulation",
        re.compile(r"\bcrontab\s+(?:-[elr]|.*\|)", re.IGNORECASE),
    ),
    (
        "persistence", "critical",
        "Systemd service creation",
        re.compile(r"(?:systemctl\s+(?:enable|start)|cp\s+.*\.service\s+/etc/systemd)", re.IGNORECASE),
    ),
    (
        "persistence", "high",
        "Write to /etc/init.d or /etc/rc.local",
        re.compile(r"""(?:>>?|cp|mv)\s+.*/etc/(?:init\.d|rc\.local)""", re.IGNORECASE),
    ),
    (
        "persistence", "high",
        "SSH authorized_keys manipulation",
        re.compile(r"""(?:>>?|cp)\s+.*\.ssh/authorized_keys""", re.IGNORECASE),
    ),
    (
        "persistence", "high",
        "LaunchAgent/LaunchDaemon (macOS persistence)",
        re.compile(r"/Library/Launch(?:Agents?|Daemons?)/", re.IGNORECASE),
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 7. network — 网络攻击
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    (
        "network", "critical",
        "Reverse shell (bash /dev/tcp)",
        re.compile(r"(?:bash|sh)\s+-i\s+.*?/dev/tcp/", re.IGNORECASE),
    ),
    (
        "network", "critical",
        "Reverse shell (python socket)",
        re.compile(r"socket\.connect\s*\(\s*\(\s*['\"].*['\"]\s*,\s*\d+", re.IGNORECASE),
    ),
    (
        "network", "critical",
        "Reverse shell (perl/ruby)",
        re.compile(r"(?:perl|ruby)\s+-e\s+.*socket", re.IGNORECASE),
    ),
    (
        "network", "high",
        "SSH tunnel / port forwarding",
        re.compile(r"ssh\s+.*-[LRD]\s+\d+:", re.IGNORECASE),
    ),
    (
        "network", "high",
        "socat port relay",
        re.compile(r"\bsocat\s+.*TCP", re.IGNORECASE),
    ),
    (
        "network", "high",
        "netcat listener",
        re.compile(r"\bnc\s+(?:-\w+\s+)*-l", re.IGNORECASE),
    ),
    (
        "network", "medium",
        "nmap port scanning",
        re.compile(r"\bnmap\s+", re.IGNORECASE),
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 8. obfuscation — 混淆绕过
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    (
        "obfuscation", "high",
        "Base64 decode + execute pattern",
        re.compile(r"(?:base64\s+(?:-d|--decode)|b64decode)\s*.*(?:\|\s*(?:ba)?sh|exec|eval)", re.IGNORECASE),
    ),
    (
        "obfuscation", "medium",
        "Base64 encode/decode usage",
        re.compile(r"(?:base64\.(?:b64decode|b64encode)|atob|btoa)\s*\(", re.IGNORECASE),
    ),
    (
        "obfuscation", "high",
        "Hex decode + execute pattern",
        re.compile(r"(?:bytes\.fromhex|binascii\.unhexlify|xxd\s+-r)\s*.*(?:exec|eval)", re.IGNORECASE),
    ),
    (
        "obfuscation", "medium",
        "Hex encoding/decoding",
        re.compile(r"(?:bytes\.fromhex|binascii\.(?:un)?hexlify|\.encode\(['\"]hex['\"])", re.IGNORECASE),
    ),
    (
        "obfuscation", "high",
        "String concatenation obfuscation (chr() chains)",
        re.compile(r"chr\s*\(\s*\d+\s*\)\s*\+\s*chr\s*\(\s*\d+\s*\)", re.IGNORECASE),
    ),
    (
        "obfuscation", "high",
        "ROT13 / codec obfuscation",
        re.compile(r"""\.(?:decode|encode)\s*\(\s*['"]rot.?13['"]""", re.IGNORECASE),
    ),
    # 不可见 unicode 由专用检测函数处理，不放在正则规则中

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 9. traversal — 路径穿越
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    (
        "traversal", "high",
        "Path traversal (../)",
        re.compile(r"\.\./\.\./", re.IGNORECASE),
    ),
    (
        "traversal", "medium",
        "Single-level path traversal (../)",
        re.compile(r"\.\./", re.IGNORECASE),
    ),
    (
        "traversal", "high",
        "Null byte path injection",
        re.compile(r"%00|\\x00|\\0", re.IGNORECASE),
    ),
    (
        "traversal", "medium",
        "URL-encoded traversal (%2e%2e)",
        re.compile(r"%2e%2e[/%5c]", re.IGNORECASE),
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 10. supply_chain — 供应链攻击
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    (
        "supply_chain", "high",
        "pip install from URL",
        re.compile(r"pip\s+install\s+(?:--index-url|--extra-index-url|-i)\s+http", re.IGNORECASE),
    ),
    (
        "supply_chain", "high",
        "pip install from git URL",
        re.compile(r"pip\s+install\s+git\+https?://", re.IGNORECASE),
    ),
    (
        "supply_chain", "high",
        "npm install from tarball/URL",
        re.compile(r"npm\s+install\s+https?://", re.IGNORECASE),
    ),
    (
        "supply_chain", "medium",
        "pip install with --pre (prerelease)",
        re.compile(r"pip\s+install\s+.*--pre\b", re.IGNORECASE),
    ),
    (
        "supply_chain", "high",
        "setup.py direct execution",
        re.compile(r"python\s+setup\.py\s+install", re.IGNORECASE),
    ),
    (
        "supply_chain", "medium",
        "npm postinstall script reference",
        re.compile(r'"postinstall"\s*:\s*"', re.IGNORECASE),
    ),
]

# 严重等级优先级（高 → 低）
_SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


class SafetyScanner:
    """Skill 内容安全扫描器.

    对齐 HermesAgent 源码 tools/skills_guard.py：
    - 80+ 正则规则覆盖 10 大类威胁
    - INSTALL_POLICY 信任矩阵
    - 不可见 Unicode 检测
    - 结构检查（文件数、大小、二进制、符号链接）
    - 四级严重等级: critical / high / medium / low
    """

    def scan(self, content: str) -> ScanResult:
        """扫描 Skill 内容，返回安全等级和详细发现.

        四级结果:
        - safe: 无发现
        - low: 仅 low 级别发现
        - medium: 最高 medium 级别
        - high: 最高 high 级别
        - critical: 存在 critical 级别发现
        """
        findings: list[Finding] = []
        lines = content.split("\n")

        # 正则规则扫描
        for line_num, line in enumerate(lines, start=1):
            for category, severity, desc, pattern in _RULES:
                for match in pattern.finditer(line):
                    findings.append(
                        Finding(
                            category=category,
                            matched_text=match.group()[:100],  # 截断防日志膨胀
                            line_number=line_num,
                            severity=severity,
                            description=desc,
                        )
                    )

        # 不可见 Unicode 检测
        for line_num, line in enumerate(lines, start=1):
            for match in _INVISIBLE_UNICODE_PATTERN.finditer(line):
                char_code = f"U+{ord(match.group()):04X}"
                findings.append(
                    Finding(
                        category="obfuscation",
                        matched_text=char_code,
                        line_number=line_num,
                        severity="high",
                        description=f"Invisible unicode character {char_code}",
                    )
                )

        # 最终等级 = 所有发现中最高等级
        level = self._compute_level(findings)
        return ScanResult(level=level, findings=findings)

    def scan_directory(self, path: str | Path) -> StructuralScanResult:
        """结构检查 — 扫描 Skill 目录的文件系统属性.

        检查项:
        - 文件数量（> MAX_SKILL_FILES 告警）
        - 单文件大小（> MAX_SKILL_FILE_SIZE 告警）
        - 二进制文件（禁止的扩展名）
        - 符号链接（可能指向系统文件）
        """
        path = Path(path)
        findings: list[StructuralFinding] = []

        if not path.exists() or not path.is_dir():
            return StructuralScanResult(passed=True, findings=[])

        files = list(path.rglob("*"))
        file_count = sum(1 for f in files if f.is_file())

        # 文件数量检查
        if file_count > MAX_SKILL_FILES:
            findings.append(
                StructuralFinding(
                    check="file_count",
                    detail=f"Skill contains {file_count} files (limit: {MAX_SKILL_FILES})",
                    severity="high",
                )
            )

        for f in files:
            if not f.is_file() and not f.is_symlink():
                continue

            # 符号链接检查
            if f.is_symlink():
                target = os.readlink(f)
                findings.append(
                    StructuralFinding(
                        check="symlink",
                        detail=f"Symlink detected: {f.name} -> {target}",
                        severity="high",
                    )
                )
                continue

            # 文件大小检查
            try:
                size = f.stat().st_size
                if size > MAX_SKILL_FILE_SIZE:
                    findings.append(
                        StructuralFinding(
                            check="file_size",
                            detail=f"File too large: {f.name} ({size:,} bytes, limit: {MAX_SKILL_FILE_SIZE:,})",
                            severity="high",
                        )
                    )
            except OSError:
                pass

            # 二进制文件检查
            if f.suffix.lower() in FORBIDDEN_EXTENSIONS:
                findings.append(
                    StructuralFinding(
                        check="binary_file",
                        detail=f"Forbidden binary file: {f.name}",
                        severity="high",
                    )
                )

        passed = len(findings) == 0
        return StructuralScanResult(passed=passed, findings=findings)

    def check_install_policy(
        self,
        trust_level: str,
        operation: str,
    ) -> str:
        """根据信任级别和操作类型，查询 INSTALL_POLICY 矩阵.

        Args:
            trust_level: "builtin" | "trusted" | "community" | "agent-created"
            operation: "read" | "write" | "execute"

        Returns:
            "allow" | "block" | "ask"
        """
        policy = INSTALL_POLICY.get(trust_level)
        if policy is None:
            return "block"  # 未知信任级别 → 阻止

        op_index = {"read": 0, "write": 1, "execute": 2}.get(operation)
        if op_index is None:
            return "block"  # 未知操作 → 阻止

        return policy[op_index]

    @staticmethod
    def _compute_level(findings: list[Finding]) -> str:
        """从发现列表计算最终安全等级."""
        if not findings:
            return "safe"

        max_severity = max(
            _SEVERITY_ORDER.get(f.severity, 0) for f in findings
        )

        for level_name, level_value in _SEVERITY_ORDER.items():
            if level_value == max_severity:
                return level_name

        return "medium"  # fallback
