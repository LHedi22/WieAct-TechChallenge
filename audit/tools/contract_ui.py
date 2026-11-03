"""Re-run the quota and mid-503 rows of the contract probe with correct building URLs (UI capture)."""
import sys
sys.path.insert(0, "audit/tools")
from contract_probe import scenario, solo_start, studio_start, sync_playwright  # noqa: E402
with sync_playwright() as pw:
    scenario(pw, "ui-quota", {"p_quota": 1.0, "quota_delay_s": 5.0}, solo_start("Substitution gives 0/0, so factor, cancel x-a and substitute again."), settle=25)
    scenario(pw, "ui-mid503", {"p_503_mid": 1.0, "p_quota": 0.0}, studio_start("advanced", "Calculus", 0))
