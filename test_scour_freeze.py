#!/usr/bin/env python3
"""Scour freeze fix + full UI pass for Foodie (390x844)."""
import asyncio, json, sys
from pathlib import Path
from playwright.async_api import async_playwright

SHOT = Path("/workspace/app/screenshots")
SHOT.mkdir(exist_ok=True)
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True}
BRANDON = {"latitude": 27.9182, "longitude": -82.2253}
NY = {"latitude": 40.7128, "longitude": -74.0060}
URL = "http://127.0.0.1:8765/index.html"

failures = []
console_store = []

def fail(msg):
    failures.append(msg)
    print("FAIL:", msg)

def ok(msg):
    print("OK:", msg)

async def ready(pg, timeout=8000):
    await pg.wait_for_function(
        """() => {
          const b = document.getElementById('scourBtn');
          if (!b) return false;
          const t = b.textContent || '';
          return !b.disabled && t === 'Scour Reviews & Rank';
        }""",
        timeout=timeout,
    )

async def location_found(pg):
    await pg.wait_for_function(
        "document.getElementById('locTitle').textContent.toLowerCase().includes('found') || document.getElementById('locTitle').textContent.toLowerCase().includes('zip')",
        timeout=20000,
    )

async def new_page(b, geo, extra_init=None):
    ctx = await b.new_context(**PHONE, geolocation=geo, permissions=["geolocation"], locale="en-US")
    pg = await ctx.new_page()
    errors = []
    logs = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    def on_console(m):
        if m.type != "error":
            return
        txt = m.text or ""
        # Chromium logs failed third-party fetches (Overpass 429/504, OSM tiles) as console.error
        if "Failed to load resource" in txt:
            return
        logs.append((m.type, txt))
    pg.on("console", on_console)
    if extra_init:
        await pg.add_init_script(extra_init)
    await pg.goto(URL, wait_until="domcontentloaded")
    return ctx, pg, errors, logs

async def btn_state(pg):
    return await pg.evaluate("""() => {
      const b = document.getElementById('scourBtn');
      return { disabled: b.disabled, text: b.textContent };
    }""")

async def results_info(pg):
    return await pg.evaluate("""() => {
      const cards = [...document.querySelectorAll('#results .result-card')];
      let pins = 0;
      if (typeof markersLayer !== 'undefined' && markersLayer) {
        markersLayer.eachLayer(() => { pins++; });
      }
      const wrap = document.getElementById('mapWrap');
      return {
        cards: cards.map(c => c.dataset.name || (c.querySelector('.name')||{}).textContent),
        n: cards.length,
        pins,
        mapVisible: !!(wrap && wrap.classList.contains('visible')),
        empty: (document.querySelector('#results .empty')||{}).textContent || '',
        note: (document.querySelector('#results .top-note')||{}).textContent || '',
        overflow: document.documentElement.scrollWidth > 390 + 2
      };
    }""")

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()

        # ——— 1. Brandon: Scour 3+ times, radius change, pins, no freeze ———
        ctx, pg, errors, logs = await new_page(b, BRANDON)
        await location_found(pg)
        await pg.select_option("#rangeSelect", "10")
        await pg.select_option("#kidsFilter", "off")

        times = []
        for i in range(4):
            t0 = asyncio.get_event_loop().time()
            await pg.click("#scourBtn")
            # Button must come back quickly (not wait on Overpass)
            try:
                await ready(pg, timeout=4000)
            except Exception as e:
                st = await btn_state(pg)
                fail(f"Scour press {i+1} did not re-enable within 4s: {st}")
                await pg.screenshot(path=str(SHOT / "phone_brandon_stuck.png"))
                break
            dt = asyncio.get_event_loop().time() - t0
            times.append(dt)
            st = await btn_state(pg)
            if "Updating map" in st["text"] or st["disabled"]:
                fail(f"Scour press {i+1} still stuck: {st}")
            info = await results_info(pg)
            if info["n"] < 1:
                fail(f"Scour press {i+1} produced no cards")
            print(f"  scour {i+1}: {dt:.2f}s cards={info['n']} pins={info['pins']} map={info['mapVisible']} names={info['cards']}")
            if i == 0:
                await pg.wait_for_timeout(400)
                await pg.screenshot(path=str(SHOT / "phone_brandon_scour.png"), full_page=False)
                if info["mapVisible"]:
                    await pg.locator("#mapWrap").scroll_into_view_if_needed()
                    await pg.wait_for_timeout(350)
                    await pg.locator("#mapWrap").screenshot(path=str(SHOT / "phone_brandon_scour_map.png"))

        info = await results_info(pg)
        if info["n"] >= 1 and info["mapVisible"] and info["pins"] >= info["n"]:
            ok(f"Brandon search completed with {info['n']} cards and {info['pins']} pins")
        elif info["n"] >= 1 and info["mapVisible"] and info["pins"] >= 3:
            # user reported only 3 pins before; we want all cards pinned
            if info["pins"] != info["n"]:
                fail(f"pin count {info['pins']} != card count {info['n']}")
            else:
                ok("pins match cards")
        else:
            fail(f"Brandon map/pins incomplete: {info}")

        # radius change then Scour again
        await pg.select_option("#rangeSelect", "5")
        await pg.click("#scourBtn")
        await ready(pg, timeout=4000)
        info5 = await results_info(pg)
        print(f"  radius 5: cards={info5['n']} pins={info5['pins']}")
        await pg.select_option("#rangeSelect", "10")
        await pg.click("#scourBtn")
        await ready(pg, timeout=4000)
        ok("Repeated Scour + radius changes re-enabled the button")

        # Talk of the Town in Brandon
        await pg.click('.chip[data-cat="talk"]')
        await pg.click("#scourBtn")
        await ready(pg, timeout=4000)
        talk = await results_info(pg)
        print(f"  talk: note={talk['note'][:80]!r} cards={talk['n']} names={talk['cards']}")
        if talk["n"] < 5:
            fail(f"Talk of the Town expected top list in Brandon, got {talk}")
        if "Talk of the Town" not in talk["note"]:
            fail(f"Talk of the Town note missing: {talk['note']}")
        # should show rating + reviews
        body = await pg.inner_text("#results")
        if "Google reviews" not in body and "reviews" not in body.lower():
            fail("Talk of the Town cards missing review counts")
        await pg.screenshot(path=str(SHOT / "phone_brandon_talk.png"), full_page=False)
        ok(f"Talk of the Town showed {talk['n']} verified places")

        # Every chip (sample several + All)
        for cat in ["All", "Asian", "BBQ", "Breakfast"]:
            sel = "all" if cat == "All" else cat
            await pg.click(f'.chip[data-cat="{sel}"]')
            await pg.click("#scourBtn")
            await ready(pg, timeout=4000)
            inf = await results_info(pg)
            print(f"  chip {cat}: cards={inf['n']}")
            if inf["n"] < 1:
                fail(f"Category {cat} produced no Brandon results")

        # Kids filter
        await pg.click('.chip[data-cat="all"]')
        await pg.select_option("#kidsFilter", "any")
        await pg.click("#scourBtn")
        await ready(pg, timeout=4000)
        kids = await results_info(pg)
        print(f"  kids any: cards={kids['n']} names={kids['cards']}")
        await pg.select_option("#kidsFilter", "off")

        # How we rank toggle
        await pg.click(".how-toggle")
        open_how = await pg.evaluate("document.getElementById('howBody').classList.contains('open')")
        if not open_how:
            fail("How we rank did not open")
        await pg.click(".how-toggle")

        # Menu + Talk of the Town menu item
        await pg.click("#menuBtn")
        await pg.wait_for_timeout(200)
        overlay_open = await pg.evaluate("document.getElementById('menuOverlay').classList.contains('open')")
        if not overlay_open:
            fail("Menu overlay did not open")
        await pg.click("text=Talk of the Town")
        await ready(pg, timeout=4000)
        talk2 = await results_info(pg)
        if talk2["n"] < 5:
            fail("Menu Talk of the Town did not render list")
        ok("Menu and Talk of the Town work")

        # Menu Gas + Specials
        await pg.click("#menuBtn")
        await pg.click("text=Gas Prices")
        gas_active = await pg.evaluate("document.getElementById('view-gas').classList.contains('active')")
        if not gas_active:
            fail("Gas view not active")
        await pg.click("text=Find Cheapest Gas")
        await pg.wait_for_timeout(300)
        gas_n = await pg.locator("#gasResults .result-card").count()
        print(f"  gas cards={gas_n}")
        if gas_n < 1:
            fail("Gas ranking produced no stations in Brandon")
        # Show on map from gas should switch back to foodie
        if gas_n:
            await pg.locator("#gasResults .map-btn").first.click()
            await pg.wait_for_timeout(400)
            foodie_active = await pg.evaluate("document.getElementById('view-foodie').classList.contains('active')")
            map_vis = await pg.evaluate("document.getElementById('mapWrap').classList.contains('visible')")
            if not foodie_active or not map_vis:
                fail(f"Gas Show on map did not reveal map (foodie={foodie_active} map={map_vis})")
            else:
                ok("Gas Show on map switched to Foodie and showed the map")

        await pg.click("#menuBtn")
        await pg.click("text=Today’s Specials")
        await pg.wait_for_timeout(300)
        spec = await pg.inner_text("#specialsResults")
        if "only available" in spec and "Brandon" in spec:
            fail("Specials treated Brandon user as outside area")
        print(f"  specials snippet: {spec[:120]!r}")

        await pg.click("#menuBtn")
        await pg.click("text=Restaurant Rankings")
        overflow = await pg.evaluate("document.documentElement.scrollWidth > 400")
        if overflow:
            fail("Horizontal overflow on 390px viewport")
        else:
            ok("No horizontal overflow at 390px")

        if errors:
            fail("Brandon pageerror: " + " | ".join(errors))
        if logs:
            fail("Brandon console.error: " + " | ".join(t for _, t in logs))
        await ctx.close()

        # ——— 2. Slow/failing Overpass+Nominatim must not freeze button ———
        ctx, pg, errors, logs = await new_page(b, BRANDON)
        await pg.route("**/*overpass*", lambda route: route.abort())
        await pg.route("**/nominatim.openstreetmap.org/**", lambda route: route.abort())
        await location_found(pg)
        await pg.click("#scourBtn")
        try:
            await ready(pg, timeout=4000)
            st = await btn_state(pg)
            info = await results_info(pg)
            if info["n"] < 1:
                fail("Failed-network Brandon search hid curated results")
            else:
                ok(f"Failed Overpass/Nominatim still showed {info['n']} curated results and re-enabled button ({st})")
        except Exception:
            st = await btn_state(pg)
            fail(f"Button frozen when Overpass/Nominatim fail: {st}")
        await pg.screenshot(path=str(SHOT / "phone_brandon_offline_apis.png"), full_page=False)
        await ctx.close()

        # Slow APIs: delay 20s then abort — button must still return immediately for curated
        async def hang(route):
            await asyncio.sleep(20)
            await route.abort()
        ctx, pg, errors, logs = await new_page(b, BRANDON)
        await pg.route("**/*overpass*", hang)
        await pg.route("**/nominatim.openstreetmap.org/**", hang)
        await location_found(pg)
        t0 = asyncio.get_event_loop().time()
        await pg.click("#scourBtn")
        try:
            await ready(pg, timeout=4000)
            dt = asyncio.get_event_loop().time() - t0
            if dt > 5:
                fail(f"Slow APIs blocked button for {dt:.1f}s")
            else:
                ok(f"Slow APIs did not block button ({dt:.2f}s)")
        except Exception:
            fail("Slow APIs froze the Scour button")
        await ctx.close()

        # ——— 3. Another city (NY): live search or empty/try-again; Talk coming soon; no console errors ———
        ctx, pg, errors, logs = await new_page(b, NY)
        await location_found(pg)
        await pg.click("#scourBtn")
        try:
            await ready(pg, timeout=18000)
        except Exception:
            st = await btn_state(pg)
            fail(f"NY Scour did not finish within 18s: {st}")
        ny = await results_info(pg)
        print(f"  NY: cards={ny['n']} empty={ny['empty'][:80]!r} pins={ny['pins']}")
        # Talk of the Town should be coming soon
        await pg.click('.chip[data-cat="talk"]')
        await pg.click("#scourBtn")
        await ready(pg, timeout=4000)
        nyt = await results_info(pg)
        txt = (nyt["empty"] or "") + nyt["note"]
        if "coming soon" not in txt.lower():
            fail(f"NY Talk of the Town should say coming soon, got {nyt}")
        else:
            ok("NY Talk of the Town shows coming-soon (no invented ratings)")
        await pg.screenshot(path=str(SHOT / "phone_ny_talk.png"), full_page=False)

        # Gas outside Brandon
        await pg.click("#menuBtn")
        await pg.click("text=Gas Prices")
        await pg.click("text=Find Cheapest Gas")
        gas_txt = await pg.inner_text("#gasResults")
        if "Brandon" not in gas_txt and "GasBuddy" not in gas_txt:
            fail(f"NY gas should explain local-only limitation: {gas_txt[:160]}")
        else:
            ok("NY gas view explains Brandon-only limitation")

        if errors:
            fail("NY pageerror: " + " | ".join(errors))
        # filter noisy third-party errors if any
        real_logs = [t for typ, t in logs if "favicon" not in t.lower()]
        if real_logs:
            fail("NY console.error: " + " | ".join(real_logs))
        await ctx.close()

        await b.close()

    print("\n==== SUMMARY ====")
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print(" -", f)
        return 1
    print("All checks passed")
    print("Screenshot:", SHOT / "phone_brandon_scour.png")
    print("Map screenshot:", SHOT / "phone_brandon_scour_map.png")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
