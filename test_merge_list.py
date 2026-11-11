#!/usr/bin/env python3
"""Asian chip merge + live list merge + Arby's geocode checks."""
import asyncio, sys
from pathlib import Path
from playwright.async_api import async_playwright
from urllib.parse import unquote

SHOT = Path("/workspace/app/screenshots")
SHOT.mkdir(exist_ok=True)
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True}
BRANDON = {"latitude": 27.9182, "longitude": -82.2253}
URL = "http://127.0.0.1:8765/index.html"
CHAINS = ["Arby's", "Olive Garden", "McDonald", "Wendy", "Taco Bell", "Burger King",
          "Chipotle", "Panera", "Chili", "IHOP", "Denny", "Texas Roadhouse",
          "Popeyes", "Chick-fil-A", "Zaxby", "Outback", "Whataburger", "Wingstop",
          "Miller's Ale House"]

async def ready(pg, timeout=8000):
    await pg.wait_for_function(
        """() => {
          const b = document.getElementById('scourBtn');
          return b && !b.disabled && b.textContent === 'Scour Reviews & Rank';
        }""",
        timeout=timeout,
    )

async def info(pg):
    return await pg.evaluate("""() => {
      const cards = [...document.querySelectorAll('#results .result-card')];
      let pins = 0;
      if (typeof markersLayer !== 'undefined' && markersLayer) markersLayer.eachLayer(() => { pins++; });
      const note = (document.querySelector('#results .top-note')||{}).textContent || '';
      const chips = [...document.querySelectorAll('#chips .chip')].map(c => ({cat: c.dataset.cat, text: c.textContent.trim(), active: c.classList.contains('active')}));
      return {
        n: cards.length,
        names: cards.map(c => c.dataset.name || (c.querySelector('.name')||{}).textContent),
        dirs: cards.map(c => ({name: c.dataset.name, dir: c.dataset.dir || '', addr: c.dataset.address || ''})),
        pins, note,
        chips,
        btn: {disabled: document.getElementById('scourBtn').disabled, text: document.getElementById('scourBtn').textContent}
      };
    }""")

async def wait_for_growth(pg, min_n, timeout=28000):
    start = asyncio.get_event_loop().time()
    last = 0
    while asyncio.get_event_loop().time() - start < timeout / 1000:
        inf = await info(pg)
        last = inf["n"]
        if last >= min_n:
            return inf
        await pg.wait_for_timeout(500)
    return await info(pg)

async def main():
    failures = []
    def fail(m):
        failures.append(m); print("FAIL:", m)
    def ok(m):
        print("OK:", m)

    async with async_playwright() as p:
        b = await p.chromium.launch()
        iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
        ctx = await b.new_context(**PHONE, geolocation=BRANDON, permissions=["geolocation"], locale="en-US", user_agent=iphone_ua)
        pg = await ctx.new_page()
        pg.on("console", lambda msg: print(f"  [console.{msg.type}] {msg.text}") if any(k in (msg.text or "") for k in ["Overpass", "live merge", "Background"]) else None)
        await pg.goto(URL, wait_until="domcontentloaded")
        await pg.wait_for_function("document.getElementById('locTitle').textContent.toLowerCase().includes('found')", timeout=20000)
        await pg.select_option("#rangeSelect", "10")
        await pg.select_option("#kidsFilter", "off")

        chips = await pg.evaluate("() => [...document.querySelectorAll('#chips .chip')].map(c => c.dataset.cat)")
        print("chips:", chips)
        for gone in ["Sushi", "Thai", "Vietnamese", "Chinese", "Japanese", "Korean", "Ramen"]:
            if gone in chips:
                fail(f"chip {gone} should have been merged into Asian")
        if "Asian" not in chips:
            fail("Asian chip missing")
        if "Indian" not in chips:
            fail("Indian chip should stay separate")
        if chips.count("Asian") != 1:
            fail("expected exactly one Asian chip")
        ok("Cuisine chips: one Asian, Indian kept separate")

        # Immediate curated list (no longer top 5)
        await pg.click("#scourBtn")
        await ready(pg, timeout=4000)
        immediate = await info(pg)
        print(f"IMMEDIATE after Scour: cards={immediate['n']} pins={immediate['pins']} note={immediate['note']!r}")
        print("  first names:", immediate["names"][:8])
        if immediate["btn"]["disabled"] or immediate["btn"]["text"] != "Scour Reviews & Rank":
            fail(f"button blocked after immediate render: {immediate['btn']}")
        if immediate["n"] <= 5:
            fail(f"immediate list still capped at {immediate['n']} (expected all curated, ~40)")
        else:
            ok(f"immediate list grew from previous 5 to {immediate['n']}")

        # Background live merge should add many more
        merged = await wait_for_growth(pg, max(80, immediate["n"] + 20), timeout=28000)
        print(f"AFTER LIVE MERGE: cards={merged['n']} pins={merged['pins']} note={merged['note']!r}")
        btn = await info(pg)
        if btn["btn"]["disabled"]:
            fail("button disabled after live merge")
        if merged["n"] <= immediate["n"]:
            fail(f"live merge did not increase the count (Overpass may have failed): {merged['n']} vs immediate {immediate['n']}")
        if merged["n"] < 80:
            fail(f"fuller list still too small: {merged['n']} (expected ~100+ live OSM places for Brandon 10 mi)")
        if merged["pins"] < merged["n"]:
            fail(f"pins {merged['pins']} < cards {merged['n']}")

        names_l = " | ".join(merged["names"]).lower()
        if "arby" not in names_l:
            fail("Arby's Valrico missing from 10-mile Brandon list")
        else:
            arby = next((d for d in merged["dirs"] if d["name"] and "arby" in d["name"].lower() and "3370" in ((d.get("addr") or "") + (d.get("dir") or ""))), None) or next(d for d in merged["dirs"] if d["name"] and "valrico" in d["name"].lower() and "arby" in d["name"].lower())
            decoded = unquote(arby["dir"] or "")
            print("Arby's directions:", decoded, "addr:", arby["addr"])
            if "3370" not in decoded or "Arby" not in decoded:
                fail(f"Arby's directions should be name+address, got {decoded}")
            if "@" in decoded and "27.937" in decoded:
                fail(f"Arby's directions still use raw coordinates: {decoded}")
            ok("Arby's present with name+address directions")

        if "olive garden" not in names_l:
            print("NOTE: Olive Garden not in visible cap/list yet (may be lower ranked or OSM-only after merge failed)")
        else:
            ok("Olive Garden present")

        found_chains = [c for c in CHAINS if any(c.lower() in (n or "").lower() for n in merged["names"])]
        print("Well-known chains present:", found_chains)

        # Asian chip
        await pg.click('.chip[data-cat="Asian"]')
        await pg.click("#scourBtn")
        await ready(pg, timeout=4000)
        asian_imm = await info(pg)
        asian = await wait_for_growth(pg, max(6, asian_imm["n"]), timeout=20000)
        print(f"ASIAN immediate={asian_imm['n']} after={asian['n']} names={asian['names'][:12]}")
        # Should include sushi/thai/chinese/viet places, not Tandoor
        asian_l = " | ".join(asian["names"]).lower()
        if "tandoor" in asian_l:
            fail("Indian restaurant Tandoor should not appear under Asian")
        expect_any = ["sushi", "liang", "kanji", "pho", "kiwa", "ploy"]
        if not any(x in asian_l for x in expect_any):
            fail(f"Asian list missing expected East/SE Asian places: {asian['names'][:15]}")
        else:
            ok("Asian chip shows combined East/SE Asian places")
        # Indian still works
        await pg.click('.chip[data-cat="Indian"]')
        await pg.click("#scourBtn")
        await ready(pg, timeout=4000)
        indian = await wait_for_growth(pg, 1, timeout=16000)
        print(f"INDIAN cards={indian['n']} names={indian['names'][:8]}")
        if indian["n"] < 1 or not any("tandoor" in (n or "").lower() or "india" in (n or "").lower() or "curry" in (n or "").lower() for n in indian["names"]):
            # Tandoor should be there immediately from curated
            if not any("tandoor" in (n or "").lower() for n in indian["names"]):
                fail(f"Indian chip did not show Tandoor: {indian['names']}")
            else:
                ok("Indian chip still separate")
        else:
            ok("Indian chip still separate")

        await pg.click('.chip[data-cat="Asian"]')
        await pg.click("#scourBtn")
        await ready(pg, timeout=4000)
        await wait_for_growth(pg, 6, timeout=18000)
        await pg.wait_for_timeout(400)
        await pg.screenshot(path=str(SHOT / "phone_brandon_asian_full.png"), full_page=False)
        # scroll so some list cards are visible with the Asian chip
        print("screenshot", SHOT / "phone_brandon_asian_full.png")

        # also capture the All list after merge for the count report
        await pg.click('.chip[data-cat="all"]')
        await pg.click("#scourBtn")
        await ready(pg, timeout=4000)
        all_imm = await info(pg)
        all_merged = await wait_for_growth(pg, max(80, all_imm["n"] + 10), timeout=28000)
        await pg.screenshot(path=str(SHOT / "phone_brandon_full_list.png"), full_page=False)
        print(f"ALL COUNT REPORT immediate={all_imm['n']} merged={all_merged['n']} pins={all_merged['pins']}")
        print("ALL note:", all_merged["note"])

        await ctx.close()
        await b.close()

    print("\n==== SUMMARY ====")
    print(f"BEFORE (previous app): 5 cards / 5 pins for Brandon 10 miles")
    print(f"AFTER immediate curated+geocoded: {all_imm['n']}")
    print(f"AFTER live merge: {all_merged['n']} cards / {all_merged['pins']} pins")
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures: print(" -", f)
        return 1
    print("All checks passed")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
