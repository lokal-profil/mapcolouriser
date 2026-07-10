// Codex MultiselectLookup-style enhancement for a country <select multiple>.
//
// The select stays in the DOM (hidden) as the form's source of truth: every
// chip add/remove writes option.selected and dispatches a bubbling `change`
// event, so form submission, getGroupState(), the live preview, and the
// no-JS fallback all keep working unchanged. The widget DOM is built with
// createElement — never innerHTML (project hook).
//
// Deliberate deviations from the Codex Vue component: selected countries are
// excluded from the menu (their chips are the removal affordance), chips are
// plain buttons (Tab reaches them, Enter/click removes), and there is no
// query highlighting. Selection behaves like keepInputOnSelection: the menu
// stays open and the query survives — preselected, so typing overwrites it.

export function createCountryMultiselect(selectEl, doc = document) {
    if (!selectEl || selectEl.dataset.enhanced) return null;
    selectEl.dataset.enhanced = "true";

    const entries = Array.from(selectEl.options).map(option => ({
        code: option.value,
        name: option.textContent.trim(),
        option,
    }));

    const baseId = selectEl.id || "countries";
    const inputId = `${baseId}-search`;
    const listboxId = `${baseId}-listbox`;

    const root = doc.createElement("div");
    root.className = "country-multiselect";

    const box = doc.createElement("div");
    box.className = "country-multiselect-box";

    const input = doc.createElement("input");
    input.type = "text";
    input.id = inputId;
    input.className = "country-multiselect-input";
    input.placeholder = "Search countries…";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", listboxId);
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("autocomplete", "off");

    const menu = doc.createElement("ul");
    menu.id = listboxId;
    menu.className = "country-multiselect-menu";
    menu.setAttribute("role", "listbox");
    menu.setAttribute("aria-label", "Countries");
    menu.hidden = true;

    box.appendChild(input);
    root.append(box, menu);

    // A display:none select with `required` makes browsers abort submit with
    // "not focusable" and no visible UI, so requiredness is transferred to a
    // customError on the visible search input (see updateValidity).
    const wasRequired = selectEl.required;
    selectEl.required = false;
    selectEl.hidden = true;

    // The entries currently rendered in the menu, in menu order.
    let filtered = [];
    let highlightIndex = -1;

    function selectedEntries() {
        return entries.filter(e => e.option.selected);
    }

    function updateValidity() {
        if (!wasRequired) return;
        input.setCustomValidity(
            selectedEntries().length ? "" : "Select at least one country.",
        );
    }

    function dispatchChange() {
        selectEl.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function renderChips() {
        box.querySelectorAll(".country-chip").forEach(el => el.remove());
        for (const entry of selectedEntries()) {
            const chip = doc.createElement("button");
            chip.type = "button";
            chip.className = "country-chip";
            chip.dataset.code = entry.code;
            chip.setAttribute("aria-label", `Remove ${entry.name}`);
            chip.append(`${entry.name} `);
            const x = doc.createElement("span");
            x.setAttribute("aria-hidden", "true");
            x.textContent = "✕";
            chip.appendChild(x);
            input.before(chip);
        }
    }

    function setHighlight(i) {
        const prev = menu.querySelector(".is-highlighted");
        if (prev) {
            prev.classList.remove("is-highlighted");
            prev.removeAttribute("aria-selected");
        }
        highlightIndex = i;
        if (i < 0 || i >= filtered.length) {
            input.removeAttribute("aria-activedescendant");
            return;
        }
        const li = menu.children[i];
        li.classList.add("is-highlighted");
        li.setAttribute("aria-selected", "true");
        input.setAttribute("aria-activedescendant", li.id);
        // Not implemented in jsdom, hence the guard.
        if (li.scrollIntoView) li.scrollIntoView({ block: "nearest" });
    }

    function matches(entry, query) {
        return (
            entry.name.toLowerCase().includes(query) ||
            entry.code.toLowerCase().startsWith(query)
        );
    }

    function renderMenu() {
        const query = input.value.trim().toLowerCase();
        filtered = entries.filter(
            e => !e.option.selected && (query === "" || matches(e, query)),
        );
        menu.replaceChildren();
        if (filtered.length === 0) {
            const li = doc.createElement("li");
            li.className = "country-multiselect-empty";
            li.textContent = "No matches";
            menu.appendChild(li);
        } else {
            for (const entry of filtered) {
                const li = doc.createElement("li");
                li.id = `${baseId}-opt-${entry.code}`;
                li.className = "country-multiselect-option";
                li.setAttribute("role", "option");
                li.dataset.code = entry.code;
                li.textContent = entry.name;
                menu.appendChild(li);
            }
        }
        // Typing pre-highlights the first match so a bare Enter picks it; the
        // full list (empty query) starts unhighlighted like Codex.
        setHighlight(query !== "" && filtered.length > 0 ? 0 : -1);
    }

    function open() {
        renderMenu();
        menu.hidden = false;
        input.setAttribute("aria-expanded", "true");
    }

    function close() {
        menu.hidden = true;
        input.setAttribute("aria-expanded", "false");
        setHighlight(-1);
    }

    function selectEntry(entry) {
        entry.option.selected = true;
        renderChips();
        updateValidity();
        dispatchChange();
        // Keep the menu open with the query in place (Codex
        // keepInputOnSelection) so further same-query matches are one
        // Enter/click away — but leave the text selected, so typing starts a
        // fresh query without manual clearing.
        renderMenu();
        input.focus();
        input.select();
    }

    function removeCode(code) {
        const entry = entries.find(e => e.code === code);
        if (!entry || !entry.option.selected) return;
        entry.option.selected = false;
        renderChips();
        updateValidity();
        dispatchChange();
        if (!menu.hidden) renderMenu();
        input.focus();
    }

    box.addEventListener("click", e => {
        const chip = e.target.closest(".country-chip");
        if (chip) {
            removeCode(chip.dataset.code);
            return;
        }
        input.focus();
    });

    // Clicking the menu must not blur the input (blur would close the menu
    // before the click lands) — swallow the mousedown, act on the click.
    menu.addEventListener("mousedown", e => e.preventDefault());
    menu.addEventListener("click", e => {
        const li = e.target.closest(".country-multiselect-option");
        if (!li) return;
        const entry = filtered.find(en => en.code === li.dataset.code);
        if (entry) selectEntry(entry);
    });

    input.addEventListener("input", open);

    input.addEventListener("keydown", e => {
        if (e.key === "ArrowDown") {
            e.preventDefault();
            if (menu.hidden) open();
            if (filtered.length) {
                setHighlight(highlightIndex < 0 ? 0 : (highlightIndex + 1) % filtered.length);
            }
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            if (menu.hidden) open();
            if (filtered.length) {
                setHighlight(highlightIndex <= 0 ? filtered.length - 1 : highlightIndex - 1);
            }
        } else if (e.key === "Enter") {
            if (!menu.hidden && highlightIndex >= 0 && highlightIndex < filtered.length) {
                e.preventDefault();
                selectEntry(filtered[highlightIndex]);
            }
        } else if (e.key === "Escape") {
            if (!menu.hidden) {
                e.preventDefault();
                close();
            }
        } else if (e.key === "Backspace" && input.value === "") {
            const selected = selectedEntries();
            if (selected.length) removeCode(selected[selected.length - 1].code);
        }
    });

    root.addEventListener("focusout", e => {
        if (!root.contains(e.relatedTarget)) close();
    });

    // Point the group's label at the visible input so click-to-focus (and the
    // label association for AT) survives the select being hidden.
    if (selectEl.id) {
        const label = doc.querySelector(`label[for="${selectEl.id}"]`);
        if (label) label.setAttribute("for", inputId);
    }

    // Mount after the wrapping label (when there is one) so chip/menu clicks
    // don't double as label-activation clicks on the input.
    const wrapLabel = selectEl.closest("label");
    (wrapLabel || selectEl).after(root);

    renderChips();
    updateValidity();

    return {
        root,
        input,
        menu,
        open,
        close,
        removeCode,
        getSelectedCodes: () => selectedEntries().map(e => e.code),
    };
}
