"""
Quick CLI test for the SAML login flow.
Usage: python test_saml_flow.py <note_number> <s_user> <s_password>
"""
import sys, logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# suppress noisy libs
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)

note   = sys.argv[1] if len(sys.argv) > 1 else "2424539"
suser  = sys.argv[2] if len(sys.argv) > 2 else ""
spw    = sys.argv[3] if len(sys.argv) > 3 else ""

if not suser or not spw:
    print("Usage: python test_saml_flow.py <note_number> <s_user> <s_password>")
    sys.exit(1)

from adapters.sap_online_fetcher import fetch_note_pdf

pdf, err = fetch_note_pdf(note, suser, spw)
if pdf:
    out = f"note_{note}.pdf"
    with open(out, "wb") as f:
        f.write(pdf)
    print(f"SUCCESS — {len(pdf)} bytes saved to {out}")
else:
    print(f"FAILED — {err}")
