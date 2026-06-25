import re


def derive_patch_from_sapk(sapk_token: str) -> str:
    """Extract numeric patch level from a SAPK string like 'SAPK-10801INS4CORE'."""
    if not sapk_token:
        return ""
    m = re.search(r"SAPK-(\d{3})(\d{2})", sapk_token, re.IGNORECASE)
    if m:
        return str(int(m.group(2)))
    return ""
