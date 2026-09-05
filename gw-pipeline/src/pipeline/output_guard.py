"""Output Content Guard — LLM response safety scanner (v4.34).

Scans LLM-generated content for:
  1. PII leakage (email, phone, IP, API keys)
  2. System prompt disclosure
  3. Harmful/injection content in outputs

All checks are regex-based — no external API calls.
"""

import re, logging
from typing import Dict, List

_log = logging.getLogger("gw-output-guard")

# PII detection patterns
_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
_PHONE_CN_RE = re.compile(r'\b(?:\+?86|\+?1)?[1-9]\d{2}[-.]?\d{4}[-.]?\d{4}\b')
_IP_RE = re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')
_API_KEY_OPENAI_RE = re.compile(r'\b(sk-[a-zA-Z0-9]{20,}|sk-ant-[a-zA-Z0-9_-]{20,})\b')
_JWT_RE = re.compile(r'\b(?:Bearer\s+)?(eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})\b')

# System prompt leakage patterns
_PROMPT_LEAK_PATTERNS = [
    re.compile(r'You are the GravitationalWave AI Agent', re.IGNORECASE),
    re.compile(r'AGENT_SYSTEM_PROMPT|system_prompt', re.IGNORECASE),
    re.compile(r'7-container Docker system', re.IGNORECASE),
    re.compile(r'Zoobot ConvNeXt-Nano', re.IGNORECASE),
    re.compile(r'CRITICAL RULE.*STOP AFTER', re.IGNORECASE),
]

# Harmful content markers
_HARMFUL_CHECKS = [
    (re.compile(r'(?:hack|exploit|bypass)\s+(?:the\s+)?(?:system|security)', re.IGNORECASE), 'security_bypass'),
    (re.compile(r'(?:delete|drop|truncate)\s+(?:all\s+)?(?:data|database)', re.IGNORECASE), 'data_destruction'),
    (re.compile(r'(?:sql\s+injection|xss|cross-?site\s+scripting)', re.IGNORECASE), 'attack_technique'),
]

CONTENT_NOTICE_PREFIX = "\n\n---\n[Content Notice] This response has been flagged for potential issues:"


async def scan_output(content: str) -> Dict:
    """Scan LLM output for safety issues.

    Returns: {safe: bool, flags: [...], score: int, content: str}
    """
    if not content or not isinstance(content, str):
        return {"safe": True, "flags": [], "score": 0, "content": content or ""}

    flags = []
    score = 0

    # Check PII patterns
    pii_checks = [
        (_EMAIL_RE, 'email'),
        (_PHONE_CN_RE, 'phone'),
        (_IP_RE, 'ip_address'),
        (_API_KEY_OPENAI_RE, 'api_key'),
        (_JWT_RE, 'jwt_token'),
    ]
    for pattern, pii_type in pii_checks:
        matches = pattern.findall(content)
        if matches:
            flags.append({
                "type": "pii",
                "subtype": pii_type,
                "count": len(matches),
                "detail": f"Detected {len(matches)} potential {pii_type} pattern(s)",
            })
            score += 30

    # Check prompt leakage
    for pattern in _PROMPT_LEAK_PATTERNS:
        if pattern.search(content):
            flags.append({
                "type": "prompt_leak",
                "detail": "Response may contain system prompt fragments",
            })
            score += 40
            break

    # Check harmful content
    for pattern, harm_type in _HARMFUL_CHECKS:
        if pattern.search(content):
            flags.append({
                "type": "harmful",
                "subtype": harm_type,
                "detail": f"Response may contain {harm_type} references",
            })
            score += 35

    safe = score < 30
    annotated_content = content

    if flags:
        flag_details = []
        for f in flags:
            flag_details.append(f"- {f['type']}: {f.get('detail', f.get('subtype', ''))}")
        annotated_content = content + CONTENT_NOTICE_PREFIX + "\n" + "\n".join(flag_details)
        _log.warning("Output guard: %d flags, score=%d", len(flags), score)

    return {
        "safe": safe,
        "flags": flags,
        "score": score,
        "content": annotated_content if not safe else content,
    }
