"""Single source of truth for product branding.

Change PRODUCT_NAME / SHORT_NAME / POWERED_BY here (and the mirrored values in
`packages/config/branding.ts` for the frontend) to rename the product without touching
any business logic anywhere else in the codebase.
"""

PRODUCT_NAME = "AlphaGasIQ"
TAGLINE = "Powered by Elavo AI"
FULL_NAME = f"{PRODUCT_NAME} — {TAGLINE}"
SHORT_NAME = "AlphaGasIQ"
