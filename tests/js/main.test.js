// JS tests for the live-preview / download / legend pipeline in static/main.js.
//
// Pure helpers (buildCss, buildLegend) are exercised in isolation. The
// stateful pieces are driven through createApp(), which lets the test set up a
// minimal DOM mirroring index.html's structure and then invoke handlers
// directly — or wire them up via app.init() and dispatch real events when
// that's what's actually under test.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildCss, buildLegend, createApp } from "../../static/main.js";

const PALETTE = ["#332288", "#88ccee", "#44aa99"];

const FIXTURE_HTML = `<!doctype html>
<html>
<body>
    <form id="colouriser-form"
          data-default-colours='${JSON.stringify(PALETTE)}'
          data-map-key="world">
        <div id="groups"></div>
        <button type="submit" id="generate-map" class="js-fallback">Generate map</button>
        <button type="submit" id="reset-groups" formaction="/reset" formnovalidate>Reset</button>
    </form>
    <button id="add-group">+ Add group</button>
    <select id="base-map-select" name="map" form="colouriser-form">
        <option value="world" selected>World</option>
        <option value="world-compact">World (compact)</option>
    </select>
    <input type="checkbox" id="toggle-circles" name="circles" form="colouriser-form" value="1" />
    <template id="group-template">
        <div class="group" data-index="__INDEX__">
            <input name="group[__INDEX__][title]" type="text" />
            <input name="group[__INDEX__][colour]" type="color" />
            <select id="countries-__INDEX__" name="group[__INDEX__][countries][]" multiple>
                <option value="se">Sweden</option>
                <option value="de">Germany</option>
            </select>
        </div>
    </template>
    <div id="map-preview"></div>
    <input id="toggle-live-preview" type="checkbox" checked />
    <button id="download-svg" disabled></button>
    <textarea id="legend-output"></textarea>
    <button id="copy-legend"></button>
</body>
</html>`;

function renderDom() {
    // DOMParser + replaceWith keeps this test setup free of any direct HTML
    // string assignment to the live document.
    const parsed = new DOMParser().parseFromString(FIXTURE_HTML, "text/html");
    document.documentElement.replaceWith(parsed.documentElement);
    document.documentElement.classList.add("js-enabled", "live-preview");
}

const FAKE_SVG = '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>';

function stubFetch({ ok = true, status = 200, body = FAKE_SVG } = {}) {
    globalThis.fetch = vi.fn(() =>
        Promise.resolve({ ok, status, text: () => Promise.resolve(body) }),
    );
}

// initMap chains 2-3 .then() handlers behind a stubbed fetch; this flush gives
// each microtask tick a chance to run before assertions.
async function flushMicrotasks() {
    for (let i = 0; i < 5; i++) await Promise.resolve();
}

describe("buildCss", () => {
    it("skips groups with no selected codes", () => {
        const css = buildCss([
            { title: "A", colour: "#ff0000", codes: [] },
            { title: "B", colour: "#00ff00", codes: ["se"] },
        ]);
        expect(css).not.toContain("/* A */");
        expect(css).toContain("/* B */");
        expect(css).toContain(".se { fill: #00ff00; }");
    });

    it("escapes a mid-edit `*/` in a title so the CSS comment can't break out", () => {
        const css = buildCss([
            { title: "evil */ break", colour: "#ff0000", codes: ["se"] },
        ]);
        expect(css).not.toContain("*/ break");
        expect(css).toContain("/* evil * / break */");
    });

    it("joins multiple country codes with a comma", () => {
        const css = buildCss([
            { title: "EU", colour: "#003399", codes: ["se", "de", "fr"] },
        ]);
        expect(css).toContain(".se, .de, .fr { fill: #003399; }");
    });

    it("returns an empty string for an empty state", () => {
        expect(buildCss([])).toBe("");
    });

    it("wraps each block with leading and trailing newlines", () => {
        const css = buildCss([{ title: "X", colour: "#abcdef", codes: ["se"] }]);
        expect(css.startsWith("\n")).toBe(true);
        expect(css.endsWith("\n")).toBe(true);
    });

    it("adds opacity: 1 to each rule when includeCircles is true", () => {
        const css = buildCss(
            [{ title: "X", colour: "#ff0000", codes: ["se"] }],
            { includeCircles: true },
        );
        expect(css).toContain(".se { fill: #ff0000; opacity: 1; }");
    });

    it("omits opacity declaration by default", () => {
        const css = buildCss([{ title: "X", colour: "#ff0000", codes: ["se"] }]);
        expect(css).not.toContain("opacity");
    });
});

describe("buildLegend", () => {
    it("emits a Legend template per group", () => {
        const out = buildLegend([
            { title: "Members", colour: "#ff0000", codes: ["se"] },
            { title: "Observers", colour: "#00ff00", codes: ["de"] },
        ]);
        expect(out).toBe("{{Legend|#ff0000|Members}}\n{{Legend|#00ff00|Observers}}");
    });

    it("skips groups with empty codes", () => {
        const out = buildLegend([
            { title: "A", colour: "#ff0000", codes: [] },
            { title: "B", colour: "#00ff00", codes: ["se"] },
        ]);
        expect(out).toBe("{{Legend|#00ff00|B}}");
    });

    it("skips groups with empty or whitespace-only title", () => {
        const out = buildLegend([
            { title: "", colour: "#ff0000", codes: ["se"] },
            { title: "   ", colour: "#0000ff", codes: ["de"] },
            { title: "Real", colour: "#00ff00", codes: ["fr"] },
        ]);
        expect(out).toBe("{{Legend|#00ff00|Real}}");
    });
});

describe("createApp", () => {
    beforeEach(() => {
        renderDom();
        stubFetch();
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.restoreAllMocks();
        delete globalThis.fetch;
        localStorage.clear();
    });

    describe("addGroup", () => {
        it("applies the palette colour at index % palette.length", () => {
            const app = createApp();
            app.addGroup();
            app.addGroup();
            app.addGroup();
            // 4th group wraps back to palette[0]
            app.addGroup();

            const colourInputs = document.querySelectorAll('input[type="color"]');
            expect(colourInputs).toHaveLength(4);
            expect(colourInputs[0].value).toBe(PALETTE[0]);
            expect(colourInputs[1].value).toBe(PALETTE[1]);
            expect(colourInputs[2].value).toBe(PALETTE[2]);
            expect(colourInputs[3].value).toBe(PALETTE[0]);
        });

        it("patches the data-index and name placeholders on the cloned template", () => {
            const app = createApp();
            app.addGroup();
            const group = document.querySelector(".group");
            expect(group.dataset.index).toBe("0");
            expect(group.querySelector('input[name="group[0][title]"]')).not.toBeNull();
            expect(group.querySelector('select[name="group[0][countries][]"]')).not.toBeNull();
        });

        it("patches id placeholders so cloned groups get unique country-select ids", () => {
            const app = createApp();
            app.addGroup();
            app.addGroup();
            const ids = Array.from(document.querySelectorAll('select[id^="countries-"]'))
                .map(el => el.id);
            expect(ids).toEqual(["countries-0", "countries-1"]);
            // No literal placeholder leaks through.
            expect(document.querySelector('[id*="__INDEX__"]')).toBeNull();
        });
    });

    describe("removeGroup", () => {
        it("removes the given group and leaves the rest intact", () => {
            const app = createApp();
            app.addGroup();
            app.addGroup();

            const groups = document.querySelectorAll(".group");
            expect(groups).toHaveLength(2);

            app.removeGroup(groups[0]);

            const remaining = document.querySelectorAll(".group");
            expect(remaining).toHaveLength(1);
            expect(remaining[0].dataset.index).toBe("1");
        });
    });

    describe("getGroupState", () => {
        it("reads title, colour, and selected codes from each group", () => {
            const app = createApp();
            app.addGroup();

            const group = document.querySelector(".group");
            group.querySelector('input[name="group[0][title]"]').value = "Members";
            group.querySelector('input[name="group[0][colour]"]').value = "#aabbcc";
            group.querySelector('option[value="se"]').selected = true;
            group.querySelector('option[value="de"]').selected = true;

            expect(app.getGroupState()).toEqual([
                { title: "Members", colour: "#aabbcc", codes: ["se", "de"] },
            ]);
        });
    });

    describe("downloadSvg", () => {
        it("calls reportValidity and aborts when the form is invalid", () => {
            const app = createApp();
            const form = document.getElementById("colouriser-form");
            vi.spyOn(form, "checkValidity").mockReturnValue(false);
            const reportSpy = vi.spyOn(form, "reportValidity").mockImplementation(() => {});
            const createObjectSpy = vi
                .spyOn(URL, "createObjectURL")
                .mockReturnValue("blob:fake");

            app.downloadSvg();

            expect(reportSpy).toHaveBeenCalledOnce();
            expect(createObjectSpy).not.toHaveBeenCalled();
            // No anchor was constructed for the (aborted) download.
            expect(document.querySelectorAll("a[download]")).toHaveLength(0);
        });
    });

    describe("initMap", () => {
        it("renders a 'Preview unavailable' message on a 404", async () => {
            stubFetch({ ok: false, status: 404 });
            const app = createApp();
            await app.initMap("atlantis");

            const preview = document.getElementById("map-preview");
            expect(preview.textContent).toMatch(/Preview unavailable/);
            expect(preview.textContent).toMatch(/HTTP 404/);
            // No SVG inserted, button stays disabled.
            expect(preview.querySelector("svg")).toBeNull();
            expect(document.getElementById("download-svg").disabled).toBe(true);
        });

        it("renders 'Preview unavailable' when DOMParser yields a parsererror", async () => {
            // Malformed XML — DOMParser doesn't throw, it returns a document
            // whose root is <parsererror>. The code must detect that.
            stubFetch({ body: "<svg" });
            const app = createApp();
            await app.initMap("world");

            const preview = document.getElementById("map-preview");
            expect(preview.textContent).toMatch(/Preview unavailable/);
            expect(preview.querySelector("svg")).toBeNull();
            expect(document.getElementById("download-svg").disabled).toBe(true);
        });

        it("enables the download button and wires the style element after a successful load", async () => {
            const app = createApp();
            app.addGroup();
            // Pre-select a country code so the initial refreshOutputs that initMap fires
            // at the end of its success path produces a real fill rule. Use a select
            // inside #groups to disambiguate from the base-map selector's options.
            document.querySelector('#groups option[value="se"]').selected = true;
            await app.initMap("world");

            const downloadBtn = document.getElementById("download-svg");
            expect(downloadBtn.disabled).toBe(false);

            const previewSvg = document.querySelector("#map-preview svg");
            expect(previewSvg).not.toBeNull();

            const styleEl = document.getElementById("map-colouriser-style");
            expect(styleEl).not.toBeNull();
            // Style element lives inside the SVG, not loose in the document.
            expect(styleEl.parentElement).toBe(previewSvg);
            // Content reflects the selected code (verifies the cross-document
            // doc.createElementNS binding works end-to-end).
            expect(styleEl.textContent).toMatch(/\.se \{ fill: #/);
        });
    });

    describe("loading placeholder", () => {
        it("installs a loading placeholder in #map-preview while the fetch is in flight", async () => {
            let resolveFetch;
            globalThis.fetch = vi.fn(() => new Promise(resolve => { resolveFetch = resolve; }));

            const app = createApp();
            const inFlight = app.initMap("world");

            const preview = document.getElementById("map-preview");
            expect(preview.querySelector(".map-loading")).not.toBeNull();
            expect(preview.textContent).toMatch(/Loading map/);
            expect(preview.textContent).toMatch(/Turn off the live preview/);

            // Let the fetch resolve so the promise chain settles cleanly.
            resolveFetch({ ok: true, status: 200, text: () => Promise.resolve(FAKE_SVG) });
            await inFlight;
        });
    });

    describe("circles toggle", () => {
        it("includes opacity in the style element when toggled on", async () => {
            const app = createApp();
            app.addGroup();
            // Select a country so the style element produces a real fill rule.
            document.querySelector('#groups option[value="se"]').selected = true;
            await app.initMap("world");

            const circles = document.getElementById("toggle-circles");
            circles.checked = true;
            // refreshOutputs reads circlesInput.checked directly; call via
            // setLivePreviewEnabled which fires refreshOutputs synchronously
            // and bypasses the 250ms requestUpdate debounce.
            app.setLivePreviewEnabled(true);

            const styleEl = document.getElementById("map-colouriser-style");
            expect(styleEl.textContent).toMatch(/\.se \{ fill: #[^;]+; opacity: 1; \}/);
        });
    });

    describe("base map selector", () => {
        it("re-fetches and gates the download button on selector change", async () => {
            const app = createApp();
            app.init();  // wires the change listener
            // Add a group so updateActionState's "no groups → disable" branch
            // isn't what gates the download button — we want to observe the
            // mapLoaded-driven gating specifically.
            app.addGroup();
            await flushMicrotasks();  // initial initMap settles, mapLoaded=true
            expect(document.getElementById("download-svg").disabled).toBe(false);

            // Switch to the compact map.
            const mapSelect = document.getElementById("base-map-select");
            mapSelect.value = "world-compact";
            mapSelect.dispatchEvent(new Event("change", { bubbles: true }));

            // The change handler resets mapLoaded synchronously before the
            // fetch resolves — download must be disabled in this interim.
            expect(document.getElementById("download-svg").disabled).toBe(true);
            expect(globalThis.fetch).toHaveBeenLastCalledWith("/maps/world-compact.svg");

            // After the fetch settles, mapLoaded flips true and download re-enables.
            await flushMicrotasks();
            expect(document.getElementById("download-svg").disabled).toBe(false);
        });
    });

    describe("live-preview persistence", () => {
        it("writes the preference to localStorage on every change", () => {
            const app = createApp();
            app.setLivePreviewEnabled(false);
            expect(localStorage.getItem("mapcolouriser:live-preview")).toBe("0");
            app.setLivePreviewEnabled(true);
            expect(localStorage.getItem("mapcolouriser:live-preview")).toBe("1");
        });

        it("syncs the checkbox to the FOUC-set html class on init", async () => {
            // Simulate a stored "off" preference: the inline FOUC script
            // would have skipped adding the live-preview class. The hardcoded
            // checked attribute in the input must not lie about the state.
            document.documentElement.classList.remove("live-preview");

            const app = createApp();
            app.init();
            await flushMicrotasks();

            expect(document.getElementById("toggle-live-preview").checked).toBe(false);
        });

        it("does not throw when localStorage access fails", () => {
            const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
                throw new Error("QuotaExceeded");
            });
            vi.spyOn(console, "warn").mockImplementation(() => {});

            const app = createApp();
            expect(() => app.setLivePreviewEnabled(false)).not.toThrow();
            expect(spy).toHaveBeenCalled();
        });
    });

    describe("setLivePreviewEnabled", () => {
        it("toggles the live-preview class and re-populates outputs on re-enable", async () => {
            const app = createApp();
            app.addGroup();
            document.querySelector('option[value="se"]').selected = true;
            await app.initMap("world");

            const styleEl = document.getElementById("map-colouriser-style");
            // Sanity: style element already populated from initMap's refreshOutputs.
            expect(styleEl.textContent).toContain(".se");

            app.setLivePreviewEnabled(false);
            expect(document.documentElement.classList.contains("live-preview")).toBe(false);

            // Mutating the form while disabled should NOT update the style.
            document.querySelector('option[value="de"]').selected = true;
            const before = styleEl.textContent;
            app.setLivePreviewEnabled(true);
            expect(document.documentElement.classList.contains("live-preview")).toBe(true);
            // Re-enable runs refreshOutputs, which picks up the new selection.
            expect(styleEl.textContent).not.toBe(before);
            expect(styleEl.textContent).toContain(".de");
        });
    });

    describe("submit handler", () => {
        it("prevents form submission when live preview is enabled", async () => {
            const app = createApp();
            app.init();
            await flushMicrotasks();

            const form = document.getElementById("colouriser-form");
            const evt = new Event("submit", { bubbles: true, cancelable: true });
            form.dispatchEvent(evt);
            expect(evt.defaultPrevented).toBe(true);
        });

        it("allows form submission when live preview is disabled", async () => {
            const app = createApp();
            app.init();
            await flushMicrotasks();
            app.setLivePreviewEnabled(false);

            const form = document.getElementById("colouriser-form");
            const evt = new Event("submit", { bubbles: true, cancelable: true });
            form.dispatchEvent(evt);
            expect(evt.defaultPrevented).toBe(false);
        });

        it("allows a submit triggered by the reset button even when live preview is on", async () => {
            const app = createApp();
            app.init();
            await flushMicrotasks();

            const form = document.getElementById("colouriser-form");
            const resetBtn = document.getElementById("reset-groups");
            // SubmitEvent isn't reliably exposed in jsdom; fake it on a plain Event.
            const evt = new Event("submit", { bubbles: true, cancelable: true });
            Object.defineProperty(evt, "submitter", { value: resetBtn });
            form.dispatchEvent(evt);
            // Submit handler must NOT preventDefault on reset.
            expect(evt.defaultPrevented).toBe(false);
        });
    });

    describe("reset button", () => {
        it("prevents the click (and therefore the submit) when confirm() is cancelled", async () => {
            const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
            const app = createApp();
            app.init();
            await flushMicrotasks();

            const resetBtn = document.getElementById("reset-groups");
            const clickEvt = new MouseEvent("click", { bubbles: true, cancelable: true });
            resetBtn.dispatchEvent(clickEvt);

            expect(confirmSpy).toHaveBeenCalledOnce();
            expect(clickEvt.defaultPrevented).toBe(true);
        });

        it("lets the click through when confirm() is accepted", async () => {
            vi.spyOn(window, "confirm").mockReturnValue(true);

            const app = createApp();
            app.init();
            await flushMicrotasks();

            const resetBtn = document.getElementById("reset-groups");
            // The production click handler is attached to the element directly,
            // so flipping the type prevents jsdom's submit-activation (which
            // logs an unrelated "requestSubmit not implemented" warning) while
            // leaving the listener under test intact.
            resetBtn.type = "button";
            const clickEvt = new MouseEvent("click", { bubbles: true, cancelable: true });
            resetBtn.dispatchEvent(clickEvt);
            resetBtn.type = "submit";

            // Click is NOT prevented — the native submit-to-formaction would proceed.
            expect(clickEvt.defaultPrevented).toBe(false);
        });
    });

    describe("updateActionState button gating", () => {
        it("disables only #generate-map (not #reset-groups) when no groups remain", () => {
            const app = createApp();
            app.addGroup();
            // Start with at least one group → Generate enabled
            expect(document.getElementById("generate-map").disabled).toBe(false);

            // Remove the only group → Generate disabled, Reset stays enabled
            app.removeGroup(document.querySelector(".group"));
            expect(document.getElementById("generate-map").disabled).toBe(true);
            expect(document.getElementById("reset-groups").disabled).toBe(false);
        });
    });

    describe("copy legend (init-wired)", () => {
        function stubClipboard(writeText) {
            Object.defineProperty(navigator, "clipboard", {
                value: { writeText },
                configurable: true,
                writable: true,
            });
        }

        it("writes the legend value to the clipboard and flashes 'Copied!'", async () => {
            const writeText = vi.fn().mockResolvedValue();
            stubClipboard(writeText);

            const app = createApp();
            app.init();
            await flushMicrotasks();

            document.getElementById("legend-output").value = "test legend";

            const copyBtn = document.getElementById("copy-legend");
            const original = copyBtn.textContent;
            copyBtn.click();
            await flushMicrotasks();

            expect(writeText).toHaveBeenCalledWith("test legend");
            expect(copyBtn.textContent).toBe("Copied!");
            // Original label restored on the timer; just verifying the flash
            // text appears is enough here.
            expect(original).not.toBe("Copied!");
        });

        it("flashes 'Copy failed' and selects the textarea on rejection", async () => {
            const writeText = vi.fn().mockRejectedValue(new Error("blocked"));
            stubClipboard(writeText);

            const app = createApp();
            app.init();
            await flushMicrotasks();

            const legendOutput = document.getElementById("legend-output");
            legendOutput.value = "test legend";
            const selectSpy = vi.spyOn(legendOutput, "select");

            const copyBtn = document.getElementById("copy-legend");
            copyBtn.click();
            await flushMicrotasks();

            expect(selectSpy).toHaveBeenCalled();
            expect(copyBtn.textContent).toBe("Copy failed");
        });
    });

    describe("listener wiring + debounce (init-wired)", () => {
        it("dispatched input events trigger a debounced style refresh", async () => {
            vi.useFakeTimers();
            const app = createApp();
            app.init();
            await flushMicrotasks();
            // initMap's success-path refreshOutputs already ran. Add a group +
            // code so subsequent edits produce visible CSS.
            app.addGroup();
            document.querySelector('option[value="se"]').selected = true;
            // Flush the addGroup-triggered debounce so we start with a known
            // style-element state.
            await vi.advanceTimersByTimeAsync(250);

            const styleEl = document.getElementById("map-colouriser-style");
            const colourInput = document.querySelector('input[type="color"]');
            colourInput.value = "#ff0000";
            colourInput.dispatchEvent(new Event("input", { bubbles: true }));

            // Before the 250ms debounce fires, the style content is unchanged.
            expect(styleEl.textContent).not.toContain("#ff0000");

            // 249ms still inside the window.
            await vi.advanceTimersByTimeAsync(249);
            expect(styleEl.textContent).not.toContain("#ff0000");

            // Crossing 250ms fires the refresh.
            await vi.advanceTimersByTimeAsync(1);
            expect(styleEl.textContent).toContain("#ff0000");
        });

        it("toggleInput change disables live preview", async () => {
            const app = createApp();
            app.init();
            await flushMicrotasks();

            const toggleInput = document.getElementById("toggle-live-preview");
            toggleInput.checked = false;
            toggleInput.dispatchEvent(new Event("change", { bubbles: true }));

            expect(document.documentElement.classList.contains("live-preview")).toBe(false);
        });
    });
});
