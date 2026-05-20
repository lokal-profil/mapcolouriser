// Group add/remove behaviour + client-side live preview.
//
// Clones <template id="group-template"> from index.html and patches the index
// placeholder in `name` and `data-index` attributes. Uses cloneNode rather
// than innerHTML to avoid any HTML-injection surface.
//
// Always fetches the prepared base SVG from /maps/<key>.svg, injects it into
// #map-preview, and appends a <style> element that we rewrite from the form
// state on every (debounced) change while live preview is enabled.
//
// Exported as an ES module: index.html loads it with <script type="module">
// and calls `createApp().init()`. Tests import the pure helpers and the
// factory directly without triggering DOM side effects.

export function buildCss(state) {
    return state
        .filter(g => g.codes.length > 0)
        .map(g => {
            // Visual-only safety net so a mid-edit `*/` typo doesn't break
            // the preview's CSS comment. The real defence against unsafe
            // titles is form.checkValidity() before Blob download.
            const safeTitle = g.title.replace(/\*\//g, "* /");
            const selector = g.codes.map(c => `.${c}`).join(", ");
            return `\n/* ${safeTitle} */\n${selector} { fill: ${g.colour}; }\n`;
        })
        .join("");
}

export function buildLegend(state) {
    // Skip groups missing either a title or country selection — a legend
    // entry without a label or without a corresponding map fill is noise.
    return state
        .filter(g => g.title.trim() && g.codes.length > 0)
        .map(g => `{{Legend|${g.colour}|${g.title}}}`)
        .join("\n");
}

export function createApp(doc = document) {
    const form = doc.getElementById("colouriser-form");
    const groupsContainer = doc.getElementById("groups");
    const addBtn = doc.getElementById("add-group");
    const tmpl = doc.getElementById("group-template");
    const previewContainer = doc.getElementById("map-preview");
    const toggleInput = doc.getElementById("toggle-live-preview");
    const downloadBtn = doc.getElementById("download-svg");
    const legendOutput = doc.getElementById("legend-output");
    const copyBtn = doc.getElementById("copy-legend");

    if (!form || !groupsContainer || !addBtn || !tmpl) {
        // Unreachable in production (the template ships all four IDs). Logged
        // so a future template rename surfaces here instead of going dead.
        console.error("map-colouriser: required DOM elements missing; aborting init", {
            form: !!form, groupsContainer: !!groupsContainer, addBtn: !!addBtn, tmpl: !!tmpl,
        });
        return null;
    }

    let palette = [];
    try {
        palette = JSON.parse(form.dataset.defaultColours || "[]");
    } catch (err) {
        console.warn("map-colouriser: failed to parse default colour palette", err);
        palette = [];
    }

    const mapKey = form.dataset.mapKey || "world";
    let livePreviewEnabled = doc.documentElement.classList.contains("live-preview");
    let userStyleEl = null;
    let updateTimer = null;
    // Gates the Download SVG button — true only once initMap has fetched and
    // parsed the base map. Stays false on fetch/parse failure.
    let mapLoaded = false;
    // Captured from the fetched SVG so the Blob download keeps the same XML
    // declaration the server-side download includes.
    let xmlDeclaration = "";

    function nextIndex() {
        const used = Array.from(groupsContainer.querySelectorAll(".group"))
            .map(el => parseInt(el.dataset.index, 10))
            .filter(n => !Number.isNaN(n));
        return used.length === 0 ? 0 : Math.max(...used) + 1;
    }

    function patchPlaceholders(root, idx) {
        const idxStr = String(idx);
        const groupEl = root.querySelector(".group");
        if (groupEl) {
            groupEl.dataset.index = idxStr;
        }
        root.querySelectorAll("[name]").forEach(el => {
            el.setAttribute("name", el.getAttribute("name").replaceAll("__INDEX__", idxStr));
        });
    }

    function applyDefaultColour(root, idx) {
        if (palette.length === 0) return;
        const colourInput = root.querySelector('input[type="color"]');
        if (colourInput) {
            colourInput.value = palette[idx % palette.length];
        }
    }

    function addGroup() {
        const idx = nextIndex();
        const fragment = tmpl.content.cloneNode(true);
        patchPlaceholders(fragment, idx);
        applyDefaultColour(fragment, idx);
        groupsContainer.appendChild(fragment);
        updateActionState();
        requestUpdate();
    }

    function removeGroup(groupEl) {
        groupEl.remove();
        updateActionState();
        requestUpdate();
    }

    function updateActionState() {
        const empty = groupsContainer.querySelectorAll(".group").length === 0;
        const generateBtn = doc.getElementById("generate-map");
        if (generateBtn) generateBtn.disabled = empty;
        if (downloadBtn) downloadBtn.disabled = empty || !mapLoaded;
    }

    function getGroupState() {
        return Array.from(groupsContainer.querySelectorAll(".group[data-index]")).map(el => {
            const idx = el.dataset.index;
            const titleEl = el.querySelector(`input[name="group[${idx}][title]"]`);
            const colourEl = el.querySelector(`input[name="group[${idx}][colour]"]`);
            const codeEls = el.querySelectorAll(`select[name="group[${idx}][countries][]"] option:checked`);
            return {
                title: titleEl ? titleEl.value : "",
                colour: colourEl ? colourEl.value : "",
                codes: Array.from(codeEls).map(o => o.value),
            };
        });
    }

    function initMap(key) {
        if (!previewContainer) return Promise.resolve();
        return fetch(`/maps/${key}.svg`)
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.text();
            })
            .then(svgText => {
                const declMatch = svgText.match(/^<\?xml[^?]*\?>/);
                if (declMatch) xmlDeclaration = declMatch[0];
                const parsedDoc = new DOMParser().parseFromString(svgText, "image/svg+xml");
                const svg = parsedDoc.documentElement;
                // DOMParser doesn't throw on malformed XML; it returns a
                // document whose root is <parsererror>. Detect and rethrow so
                // the catch handler below renders a useful message.
                if (svg.nodeName === "parsererror" || svg.getElementsByTagName("parsererror").length) {
                    throw new Error("base map SVG failed to parse");
                }
                previewContainer.replaceChildren(svg);
                userStyleEl = doc.createElementNS("http://www.w3.org/2000/svg", "style");
                userStyleEl.id = "map-colouriser-style";
                svg.appendChild(userStyleEl);
                mapLoaded = true;
                refreshOutputs();
                updateActionState();
            })
            .catch(err => {
                console.error("map-colouriser: failed to load base map", err);
                previewContainer.textContent =
                    `Preview unavailable (${err.message}). Try reloading the page, or submit the form to render server-side.`;
            });
    }

    function rebuildPreview(state) {
        if (!livePreviewEnabled || !userStyleEl) return;
        userStyleEl.textContent = buildCss(state);
    }

    function rebuildLegend(state) {
        if (!livePreviewEnabled || !legendOutput) return;
        const legend = buildLegend(state);
        legendOutput.value = legend;
        // Grow with content; floor at 2 so the textarea is visible when empty.
        legendOutput.rows = Math.max(2, legend ? legend.split("\n").length : 0);
    }

    function refreshOutputs() {
        const state = getGroupState();
        rebuildPreview(state);
        rebuildLegend(state);
    }

    function requestUpdate() {
        if (!livePreviewEnabled) return;
        clearTimeout(updateTimer);
        updateTimer = setTimeout(refreshOutputs, 250);
    }

    function setLivePreviewEnabled(enabled) {
        livePreviewEnabled = enabled;
        doc.documentElement.classList.toggle("live-preview", enabled);
        if (enabled) refreshOutputs();
        updateActionState();
    }

    function downloadSvg() {
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        const svg = previewContainer.querySelector("svg");
        const body = new XMLSerializer().serializeToString(svg);
        const xml = xmlDeclaration ? `${xmlDeclaration}\n${body}` : body;
        const blob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = doc.createElement("a");
        a.href = url;
        a.download = "map.svg";
        doc.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    function init() {
        addBtn.addEventListener("click", addGroup);

        groupsContainer.addEventListener("click", function (e) {
            if (e.target.matches(".remove-group")) {
                const groupEl = e.target.closest(".group");
                if (groupEl) {
                    removeGroup(groupEl);
                }
            }
        });

        form.addEventListener("input", requestUpdate);
        form.addEventListener("change", requestUpdate);

        if (toggleInput) {
            toggleInput.addEventListener("change", e => setLivePreviewEnabled(e.target.checked));
        }
        if (downloadBtn) {
            downloadBtn.addEventListener("click", downloadSvg);
        }
        if (copyBtn && legendOutput) {
            copyBtn.addEventListener("click", async () => {
                const original = copyBtn.textContent;
                try {
                    await navigator.clipboard.writeText(legendOutput.value);
                    copyBtn.textContent = "Copied!";
                    setTimeout(() => { copyBtn.textContent = original; }, 1000);
                } catch (err) {
                    // Insecure context or permission denied — fall back to selecting
                    // the text so the user can copy manually with Ctrl+C.
                    console.warn("map-colouriser: clipboard write failed, falling back to selection", err);
                    legendOutput.select();
                    copyBtn.textContent = "Copy failed";
                    setTimeout(() => { copyBtn.textContent = original; }, 2000);
                }
            });
        }

        form.addEventListener("submit", e => {
            // Reset always passes through — it's the user's deliberate "start
            // over" action and posts to /reset, not /generate. Otherwise live
            // preview swallows Enter-key and Generate-map submissions (the
            // submit button is CSS-hidden in that mode); explicit Download SVG
            // click remains the only way to download.
            if (e.submitter && e.submitter.id === "reset-groups") return;
            if (livePreviewEnabled) e.preventDefault();
        });

        const resetBtn = doc.getElementById("reset-groups");
        if (resetBtn) {
            resetBtn.addEventListener("click", e => {
                if (!confirm("Reset all groups? Your current selections will be cleared.")) {
                    e.preventDefault();
                }
            });
        }

        updateActionState();
        initMap(mapKey);
    }

    return {
        init,
        // Internal handlers exposed for tests and used by init() to wire up
        // listeners. Direct invocation in tests is often clearer than
        // synthesising the event that would dispatch the same handler.
        addGroup,
        removeGroup,
        downloadSvg,
        initMap,
        setLivePreviewEnabled,
        getGroupState,
    };
}
