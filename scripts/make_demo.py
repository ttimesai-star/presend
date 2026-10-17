"""Build docs/demo/presend_demo.mp4 from the screenshots in docs/img (needs ffmpeg and edge-tts).

Narration is synthetic (edge-tts). Run: python scripts/make_demo.py
"""
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "docs" / "img"
OUT = ROOT / "docs" / "demo" / "presend_demo.mp4"
W, H = 1280, 720
BG = (15, 23, 32)
FG = (230, 237, 243)
MUT = (139, 155, 171)
ACC = (62, 99, 221)
VOICE = "en-US-AndrewNeural"
FONT = "C:/Windows/Fonts/segoeui.ttf"
FONT_B = "C:/Windows/Fonts/segoeuib.ttf"
MONO = "C:/Windows/Fonts/consola.ttf"


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def wrap(draw, text, f, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def shot(name, box, caption):
    """Screenshot crop fitted above a caption bar."""
    im = Image.open(IMG / name).convert("RGB").crop(box)
    cap_h = 92
    scale = min((W - 40) / im.width, (H - cap_h - 30) / im.height)
    im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(im, ((W - im.width) // 2, 15))
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, H - cap_h, W, H], fill=(22, 33, 45))
    d.rectangle([0, H - cap_h, 8, H], fill=ACC)
    f = font(FONT_B, 26)
    y = H - cap_h + 14
    for line in wrap(d, caption, f, W - 60)[:2]:
        d.text((30, y), line, font=f, fill=FG)
        y += 34
    return canvas


def card(title, lines, mono=None):
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    d.text((80, 90), title, font=font(FONT_B, 54), fill=FG)
    y = 190
    for ln in lines:
        for part in wrap(d, ln, font(FONT, 30), W - 160):
            d.text((80, y), part, font=font(FONT, 30), fill=MUT)
            y += 42
        y += 10
    if mono:
        d.rounded_rectangle([70, y + 10, W - 70, y + 30 + 34 * len(mono)], 12, fill=(11, 17, 24))
        yy = y + 22
        for m in mono:
            d.text((95, yy), m, font=font(MONO, 22), fill=(124, 180, 255))
            yy += 34
    return canvas


def term(title, lines, size=19):
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([30, 25, W - 30, H - 25], 14, fill=(11, 17, 24), outline=(36, 49, 63), width=2)
    for i, c in enumerate([(229, 72, 77), (245, 165, 36), (48, 164, 108)]):
        d.ellipse([52 + i * 26, 45, 68 + i * 26, 61], fill=c)
    d.text((140, 41), title, font=font(FONT, 20), fill=MUT)
    f = font(MONO, size)
    y = 85
    for ln in lines:
        col = (229, 72, 77) if "[STOP]" in ln or "verdict: STOP" in ln else (245, 165, 36) if "[CAUTION]" in ln             else (48, 164, 108) if "verdict: OK" in ln or "[INFO]" in ln else FG if ln.startswith("$") else MUT
        for part in [ln[i:i + 105] for i in range(0, max(len(ln), 1), 105)]:
            d.text((55, y), part, font=f, fill=col)
            y += size + 7
    return canvas


def cli_lines():
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    from presend import BlockscoutClient, check_payment
    from presend.cli import render_report
    from replay import ReplaySession
    c = BlockscoutClient(api_key="x", session=ReplaySession("may2024_wbtc.json.gz"), min_interval=0)
    rep = check_payment(c, "0x1E227979f0b5BC691a70DEaed2e0F39a6F538FD5",
                        "0xd9A1C3788D81257612E2581A6ea0aDa244853a91", as_of_block=19789008,
                        use_labels=False, max_pages=3)
    out = [ln for ln in render_report(rep).splitlines() if not ln.strip().startswith("https://eth")]
    return ["$ presend check --from 0x1E227979...8FD5 --to 0xd9A1C378...3a91 --as-of-block 19789008 --no-labels"]         + out + ["$ echo $?", "2"]


SCENES = [
    (lambda: card("PreSend", ["Check a recipient against your own on-chain history before you pay.",
                              "Stops address-poisoning look-alikes, spoofed 'from you' transfers and fake tokens.",
                              "Data: Blockscout PRO API. For people and for AI agents."]),
     "This is PreSend. Before a wallet, or an AI agent, sends money, PreSend checks the recipient "
     "against the sender's own on-chain history, using the Blockscout PRO API."),
    (lambda: card("The problem: address poisoning", [
        "Wallets and explorers shorten addresses to 0xd9A1...3a91. Attackers generate a vanity address with the same ends.",
        "Then they plant it in your history: a zero-value transfer, a fake token, or a spoofed 'transfer from you'.",
        "Next time you copy a 'recent recipient', you pay the attacker. AI agents that reuse past counterparties have the same risk."]),
     "The problem is address poisoning. Wallets shorten addresses to the first and last few characters. "
     "Attackers generate a vanity address with the same ends, and plant it in your history with a zero value "
     "transfer, a fake token, or a spoofed transfer that seems to come from you. The next time you copy a recent "
     "recipient, you pay the attacker. AI agents that reuse past counterparties are exposed in the same way."),
    (lambda: shot("04_blockscout_spoof_tx.png", (130, 160, 1240, 900),
                  "Blockscout Explorer: this 'transfer from the victim' was sent by someone else"),
     "On the third of May 2024, an attacker's transaction made a fake token log a transfer from the "
     "victim's wallet to a look-alike address. Blockscout shows that the victim never signed it. "
     "About an hour later the victim copied that address from history and sent 1,155 wrapped bitcoin."),
    (lambda: shot("05_blockscout_fake_address.png", (130, 200, 1240, 680),
                  "Today Blockscout labels the fake address 'Phish / Hack' - but not on 3 May 2024"),
     "Today, Blockscout labels the fake address as phishing. But on the morning of the theft there was no label yet. "
     "A useful check has to work before anyone has reported the address."),
    (lambda: shot("01_replay_fake_stop.png", (220, 105, 1060, 470),
                  "Replay one block before the theft, Blockscout scam labels switched off"),
     "PreSend can replay a check at any block. We go back to one block before the theft, and switch "
     "off Blockscout's scam labels, because they were added later."),
    (lambda: shot("01_replay_fake_stop.png", (220, 485, 1060, 1030),
                  "Verdict STOP: spoofed transfer + look-alike of an address the wallet really paid"),
     "The verdict is stop. The only link between the wallet and this address is a spoofed transfer, "
     "and the address imitates one the wallet really paid earlier that morning: same first four and last six "
     "characters. Every finding links to the evidence on Blockscout."),
    (lambda: shot("02_replay_real_ok.png", (220, 270, 1060, 690),
                  "Same moment, the real address: OK, known recipient"),
     "The same check for the real address, at the same moment, returns OK: a known recipient."),
    (lambda: term("presend CLI, replay of 3 May 2024 (exit code 2 = STOP)", cli_lines()),
     "The same check from the command line. The exit code is two for stop, one for caution and zero for OK, "
     "so it can guard a payment script or a CI job."),
    (lambda: shot("03_scan.png", (220, 485, 1060, 1030),
                  "Scan: every poisoning attempt against the wallet, and which one was paid"),
     "Scan mode lists every poisoning attempt against a wallet, from transactions and token transfers, "
     "and shows which fake address was actually paid."),
    (lambda: card("How Blockscout PRO API powers it", [
        "/addresses/{wallet}/transactions and /token-transfers: who you really paid, and what reached you.",
        "/transactions/{hash}: who actually sent a 'transfer from you'.",
        "/addresses/{addr}: scam flag, reputation, phishing tags. /counters: how fresh the recipient is.",
        "/tokens/{addr}: fake symbols such as Cyrillic 'WBTC', ERC-20 'ETH', major symbol without price.",
        "One key, one base URL, chain_id in the path. A check costs 10-20 calls on the free tier."]),
     "Every finding is built from Blockscout PRO API data. Transactions and token transfers tell us who the wallet "
     "really paid and what reached it. The transaction endpoint tells us who actually sent a transfer that seems to "
     "come from you. The address endpoint gives the scam flag, reputation and phishing tags, and the token endpoint "
     "exposes fake symbols, like wrapped bitcoin spelled with Cyrillic letters. One key covers every chain, and a "
     "check costs ten to twenty calls on the free tier."),
    (lambda: card("Architecture", [
        "client.py: PRO API client - keyset pagination, replay skips newer pages, retries, 5 RPS pacing, credit tracking.",
        "analysis.py: pure rules, no network - look-alike, spoof, fake token, labels. Unit-tested.",
        "check.py: verdict STOP / CAUTION / OK with Blockscout Explorer links as evidence.",
        "Interfaces: CLI with exit codes, local web page (key stays server-side), MCP server for agents."]),
     "The design is simple. A small client handles pagination, retries and rate limits. The rules are pure functions "
     "with no network, so they are fully unit tested. The check combines them into a verdict with links to "
     "Blockscout Explorer as evidence, and three interfaces sit on top."),
    (lambda: card("For AI agents: MCP", ["presend_check returns STOP / CAUTION / OK with Blockscout evidence links.",
                                         "An agent that pays by x402 or a plain transfer calls it first."],
                  ["presend check --from 0x1E22...8FD5 --to 0xd9A1...3a91 \\",
                   "  --as-of-block 19789008 --no-labels     # exit 2 = STOP",
                   '{"mcpServers": {"presend": {"command": "presend-mcp"}}}']),
     "PreSend runs as a command line tool with exit codes, as a local web page, and as an MCP server, "
     "so an AI agent can call presend check before any payment and refuse when the verdict is stop."),
    (lambda: card("Honest limits", [
        "History window: last 6 pages (300 items) by default; busy wallets need --pages.",
        "Look-alike rule: 7+ matching hex characters at both ends, at least 3 at each.",
        "Prototype: no external users yet. It warns; it does not block a wallet.",
        "Sprint 2: deeper history on demand, more chains, a watch mode for new poisoning attempts."]),
     "Some honest limits. By default PreSend reads the last three hundred items of history, so busy wallets need "
     "more pages. The look alike rule needs seven matching characters at the two ends. And this is a prototype: it "
     "warns, it does not block. In sprint two we plan deeper history, more chains and a watch mode."),
    (lambda: card("github.com/ttimesai-star/presend", ["Open source, MIT. Python. 39 tests on recorded Blockscout data, CI green. Reviewed by Google Jules.",
                                                      "Prototype: Sprint 1 of the Blockscout PRO API Buildathon.",
                                                      "Next: more chains, deeper history, a watch mode for new poisoning attempts."]),
     "PreSend is open source, with thirty nine tests on recorded Blockscout data, and an external code review. "
     "It is a prototype built for the Blockscout PRO API Buildathon. Thank you."),
]


async def tts(text, path):
    await edge_tts.Communicate(text, VOICE, rate="+4%").save(str(path))


def dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
                          str(path)], capture_output=True, text=True).stdout
    return float(json.loads(out)["format"]["duration"])


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="presend_demo_"))
    parts = []
    for i, (mk, text) in enumerate(SCENES):
        png, mp3, mp4 = tmp / f"s{i}.png", tmp / f"s{i}.mp3", tmp / f"s{i}.mp4"
        mk().save(png)
        asyncio.run(tts(text, mp3))
        d = dur(mp3) + 0.7
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-i", str(mp3),
                        "-af", "apad", "-t", f"{d:.2f}", "-c:v", "libx264", "-tune", "stillimage",
                        "-pix_fmt", "yuv420p", "-r", "25", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                        str(mp4)], check=True)
        parts.append(mp4)
        print(f"scene {i}: {d:.1f}s")
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", str(OUT)], check=True)
    print("written", OUT, f"{dur(OUT):.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
