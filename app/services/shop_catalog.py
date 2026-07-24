"""Catalog of downloadable products sold on the external Lemon Squeezy shop.

Keys are Lemon Squeezy **variant IDs** (strings). Fill these in from your
Lemon dashboard (Product → Variants → ID).

``file`` is a filename relative to ``PURCHASE_FILES_DIR`` (defaults to
``instance/purchase_files/``). Put the real PDFs / notebooks there on the
server (or on the Render disk) — they are never served as public static URLs.
"""

# variant_id -> product metadata
PURCHASE_PRODUCTS: dict[str, dict] = {
    # --- placeholder example (replace with your real Lemon variant IDs) ---
    "REPLACE_WITH_VARIANT_ID": {
        "name": "Example Guide",
        "description": "A short description shown on My space.",
        "file": "example-guide.pdf",
    },
    # "12345678": {
    #     "name": "Healing Notebook",
    #     "description": "Printable worksheets for the first 30 days.",
    #     "file": "healing-notebook.pdf",
    # },
}


def catalog_entry(variant_id: str | None) -> dict | None:
    """Return the mapping entry for a Lemon variant id, or None."""
    if not variant_id:
        return None
    return PURCHASE_PRODUCTS.get(str(variant_id).strip())


def display_name(variant_id: str | None, fallback: str = "") -> str:
    entry = catalog_entry(variant_id)
    if entry and entry.get("name"):
        return entry["name"]
    return (fallback or "").strip() or "Your download"
