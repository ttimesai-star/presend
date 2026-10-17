"""Record the May 2024 WBTC address-poisoning case into tests/fixtures (needs BLOCKSCOUT_API_KEY)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from presend import BlockscoutClient, check_payment, scan_wallet  # noqa: E402
from replay import RecordingSession  # noqa: E402

VICTIM = "0x1E227979f0b5BC691a70DEaed2e0F39a6F538FD5"
FAKE = "0xd9A1C3788D81257612E2581A6ea0aDa244853a91"
REAL = "0xd9A1b0B1e1aE382DbDc898Ea68012FfcB2853a91"
BLOCK = 19789008  # one block before the 1,155 WBTC transfer (tx in block 19789009)

sess = RecordingSession()
c = BlockscoutClient(chain_id=1, session=sess)
print(check_payment(c, VICTIM, FAKE, as_of_block=BLOCK, use_labels=False, max_pages=3).verdict)
print(check_payment(c, VICTIM, REAL, as_of_block=BLOCK, use_labels=False, max_pages=3).verdict)
print(check_payment(c, VICTIM, FAKE, max_pages=2).verdict)
print(len(scan_wallet(c, VICTIM, max_pages=14)["attempts"]))
print("saved", sess.save("may2024_wbtc.json.gz"), len(sess.store), "answers")
