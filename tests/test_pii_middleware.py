import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[1] / "src" / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from pii_masking import PIIMasker


def test_pii_masker_masks_common_patterns():
    masker = PIIMasker()
    raw = "Email jane.doe@example.com or call (415) 555-0199. SSN 123-45-6789 account 123456789012."
    masked = masker.mask_text(raw)

    assert "jane.doe@example.com" not in masked
    assert "(415) 555-0199" not in masked
    assert "123-45-6789" not in masked
    assert "123456789012" not in masked
    assert "[MASKED_EMAIL]" in masked
    assert "[MASKED_PHONE]" in masked
    assert "[MASKED_SSN]" in masked
    assert "[MASKED_ACCOUNT]" in masked


def test_pii_masker_masks_nested_payloads():
    masker = PIIMasker()
    payload = {
        "query": "reach me at jane@example.com",
        "metadata": {"phone": "415-555-0142"},
        "events": ["customer ssn 123-45-6789", {"account": "123456789012"}],
    }

    masked = masker.mask_any(payload)
    assert masked["query"] == "reach me at [MASKED_EMAIL]"
    assert masked["metadata"]["phone"] == "[MASKED_PHONE]"
    assert masked["events"][0] == "customer ssn [MASKED_SSN]"
    assert masked["events"][1]["account"] == "[MASKED_ACCOUNT]"
