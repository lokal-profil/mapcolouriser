// Group add/remove behaviour for the colouriser form.
//
// Clones <template id="group-template"> from index.html and patches the index
// placeholder in `name` and `data-index` attributes. Uses cloneNode rather
// than innerHTML to avoid any HTML-injection surface.

(function () {
    const form = document.getElementById("colouriser-form");
    const groupsContainer = document.getElementById("groups");
    const addBtn = document.getElementById("add-group");
    const tmpl = document.getElementById("group-template");

    if (!form || !groupsContainer || !addBtn || !tmpl) {
        return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');

    let palette = [];
    try {
        palette = JSON.parse(form.dataset.defaultColours || "[]");
    } catch {
        palette = [];
    }

    function updateSubmitState() {
        if (!submitBtn) return;
        submitBtn.disabled = groupsContainer.querySelectorAll(".group").length === 0;
    }

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
        updateSubmitState();
    }

    function removeGroup(groupEl) {
        groupEl.remove();
        updateSubmitState();
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

    updateSubmitState();
})();
