// Group add/remove behaviour + client-side live preview.
//
// Clones <template id="group-template"> from index.html and patches the index
// placeholder in `name` and `data-index` attributes. Uses cloneNode rather
// than innerHTML to avoid any HTML-injection surface.
//
// When live preview is enabled, fetches the prepared base SVG from
// /maps/<key>.svg, injects it into #map-preview, and appends a <style> element
// that we rewrite from the form state on every (debounced) change.

(function () {
    const form = document.getElementById("colouriser-form");
    const groupsContainer = document.getElementById("groups");
    const addBtn = document.getElementById("add-group");
    const tmpl = document.getElementById("group-template");
    const previewContainer = document.getElementById("map-preview");
    const toggleInput = document.getElementById("toggle-live-preview");
    const downloadBtn = document.getElementById("download-svg");

    if (!form || !groupsContainer || !addBtn || !tmpl) {
        return;
    }

    let palette = [];
    try {
        palette = JSON.parse(form.dataset.defaultColours || "[]");
    } catch {
        palette = [];
    }

    const mapKey = form.dataset.mapKey || "world";
    let livePreviewEnabled = document.documentElement.classList.contains("live-preview");
    let userStyleEl = null;
    let updateTimer = null;
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
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = empty;
        if (downloadBtn) downloadBtn.disabled = empty;
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

    function buildCss(state) {
        return state
            .filter(g => g.codes.length > 0)
            .map(g => {
                // Visual-only safety net so a mid-edit `*/` typo doesn't break
                // the preview's CSS comment. The real defence against unsafe
                // titles is form.checkValidity() before Blob download.
                const safeTitle = g.title.replace(/\*\//g, "* /");
                const selector = g.codes.map(c => `.${c}`).join(", ");
                return `/* ${safeTitle} */\n${selector} { fill: ${g.colour}; }`;
            })
            .join("\n\n");
    }

    function initMap(key) {
        if (!previewContainer) return;
        fetch(`/maps/${key}.svg`)
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.text();
            })
            .then(svgText => {
                const declMatch = svgText.match(/^<\?xml[^?]*\?>/);
                if (declMatch) xmlDeclaration = declMatch[0];
                const doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
                const svg = doc.documentElement;
                previewContainer.replaceChildren(svg);
                userStyleEl = document.createElementNS("http://www.w3.org/2000/svg", "style");
                userStyleEl.id = "user-style";
                svg.appendChild(userStyleEl);
                rebuildPreview();
            })
            .catch(err => {
                previewContainer.textContent = `Preview unavailable (${err.message}).`;
            });
    }

    function rebuildPreview() {
        if (!livePreviewEnabled || !userStyleEl) return;
        userStyleEl.textContent = buildCss(getGroupState());
    }

    function requestUpdate() {
        if (!livePreviewEnabled) return;
        clearTimeout(updateTimer);
        updateTimer = setTimeout(rebuildPreview, 250);
    }

    function setLivePreviewEnabled(enabled) {
        livePreviewEnabled = enabled;
        document.documentElement.classList.toggle("live-preview", enabled);
        if (enabled) rebuildPreview();
        updateActionState();
    }

    function downloadSvg() {
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        const svg = previewContainer && previewContainer.querySelector("svg");
        if (!svg) return;
        const body = new XMLSerializer().serializeToString(svg);
        const xml = xmlDeclaration ? `${xmlDeclaration}\n${body}` : body;
        const blob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "map.svg";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

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

    // Live preview swallows Enter-key submissions on the form (the submit
    // button itself is CSS-hidden in that mode); explicit Download SVG click
    // remains the only way to download.
    form.addEventListener("submit", e => {
        if (livePreviewEnabled) e.preventDefault();
    });

    updateActionState();
    initMap(mapKey);
})();
