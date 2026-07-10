// Unit tests for the country multiselect enhancement (country_multiselect.js).
//
// The widget is driven through the handle createCountryMultiselect returns
// plus dispatched DOM events; the fixture mirrors index.html's label-wrapped
// select. Group 0 is `required` with a pre-selected country (the import /
// session-restore case); group 1 is optional and empty.

import { beforeEach, describe, expect, it, vi } from "vitest";

import { createCountryMultiselect } from "../../static/country_multiselect.js";

const FIXTURE_HTML = `<!doctype html>
<html>
<body>
    <form id="f">
        <label for="countries-0">Countries
            <select id="countries-0" name="group[0][countries][]" multiple required>
                <option value="se">Sweden</option>
                <option value="sn">Senegal</option>
                <option value="de" selected>Germany</option>
                <option value="dk">Denmark</option>
                <option value="fi">Finland</option>
                <option value="no">Norway</option>
            </select>
        </label>
        <label for="countries-1">Countries
            <select id="countries-1" name="group[1][countries][]" multiple>
                <option value="se">Sweden</option>
                <option value="de">Germany</option>
            </select>
        </label>
    </form>
</body>
</html>`;

function renderDom() {
    // DOMParser + replaceWith keeps this test setup free of any direct HTML
    // string assignment to the live document (project hook).
    const parsed = new DOMParser().parseFromString(FIXTURE_HTML, "text/html");
    document.documentElement.replaceWith(parsed.documentElement);
}

function enhance(id = "countries-0") {
    return createCountryMultiselect(document.getElementById(id));
}

function type(widget, text) {
    widget.input.value = text;
    widget.input.dispatchEvent(new Event("input", { bubbles: true }));
}

function press(widget, key) {
    widget.input.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
    );
}

function menuTexts(widget) {
    return Array.from(
        widget.menu.querySelectorAll(".country-multiselect-option"),
    ).map(li => li.textContent);
}

function chips(widget) {
    return Array.from(widget.root.querySelectorAll(".country-chip"));
}

beforeEach(() => {
    renderDom();
});

describe("enhancement", () => {
    it("hides the select, drops its required flag, and marks it enhanced", () => {
        const select = document.getElementById("countries-0");
        enhance();
        expect(select.hidden).toBe(true);
        expect(select.required).toBe(false);
        expect(select.dataset.enhanced).toBe("true");
    });

    it("is a no-op on an already-enhanced select", () => {
        enhance();
        expect(enhance()).toBeNull();
        expect(document.querySelectorAll(".country-multiselect")).toHaveLength(1);
    });

    it("retargets the group label to the search input", () => {
        enhance();
        const label = document.querySelector("label");
        expect(label.getAttribute("for")).toBe("countries-0-search");
        expect(document.getElementById("countries-0-search")).not.toBeNull();
    });

    it("mounts the widget outside the wrapping label", () => {
        const widget = enhance();
        expect(widget.root.closest("label")).toBeNull();
        expect(widget.root.closest("form")).not.toBeNull();
    });

    it("renders chips for pre-selected options", () => {
        const widget = enhance();
        const chipEls = chips(widget);
        expect(chipEls).toHaveLength(1);
        expect(chipEls[0].textContent).toContain("Germany");
        expect(chipEls[0].getAttribute("aria-label")).toBe("Remove Germany");
        expect(widget.getSelectedCodes()).toEqual(["de"]);
    });

    it("sets up the combobox ARIA contract on the input and menu", () => {
        const widget = enhance();
        expect(widget.input.getAttribute("role")).toBe("combobox");
        expect(widget.input.getAttribute("aria-expanded")).toBe("false");
        expect(widget.input.getAttribute("aria-controls")).toBe("countries-0-listbox");
        expect(widget.input.getAttribute("aria-autocomplete")).toBe("list");
        expect(widget.menu.getAttribute("role")).toBe("listbox");
        expect(widget.menu.hidden).toBe(true);
    });
});

describe("filtering", () => {
    it("matches name substrings case-insensitively", () => {
        const widget = enhance();
        type(widget, "MARK");
        expect(widget.menu.hidden).toBe(false);
        expect(menuTexts(widget)).toEqual(["Denmark"]);
    });

    it("matches alpha-2 codes by prefix", () => {
        const widget = enhance();
        // "sn" appears in no display name; only Senegal's code matches.
        type(widget, "sn");
        expect(menuTexts(widget)).toEqual(["Senegal"]);
    });

    it("excludes already-selected countries from the menu", () => {
        const widget = enhance();
        type(widget, "german");
        expect(menuTexts(widget)).toEqual([]);
        expect(widget.menu.textContent).toContain("No matches");
    });

    it("shows all unselected countries on ArrowDown with an empty input", () => {
        const widget = enhance();
        press(widget, "ArrowDown");
        expect(widget.menu.hidden).toBe(false);
        // 6 options minus the pre-selected Germany.
        expect(menuTexts(widget)).toHaveLength(5);
        expect(menuTexts(widget)).not.toContain("Germany");
    });

    it("shows a non-selectable 'No matches' row and ignores Enter on it", () => {
        const widget = enhance();
        type(widget, "zzz");
        expect(widget.menu.textContent).toContain("No matches");
        press(widget, "Enter");
        expect(widget.getSelectedCodes()).toEqual(["de"]);
    });
});

describe("selection", () => {
    it("click-selecting adds a chip, checks the option, and fires change", () => {
        const widget = enhance();
        const select = document.getElementById("countries-0");
        const onChange = vi.fn();
        document.getElementById("f").addEventListener("change", onChange);

        type(widget, "fin");
        widget.menu.querySelector('[data-code="fi"]').click();

        expect(select.querySelector('option[value="fi"]').selected).toBe(true);
        expect(widget.getSelectedCodes()).toEqual(["de", "fi"]);
        expect(chips(widget)).toHaveLength(2);
        expect(onChange).toHaveBeenCalledOnce();
        expect(onChange.mock.calls[0][0].target).toBe(select);
    });

    it("Enter selects the highlighted match (typing pre-highlights the first)", () => {
        const widget = enhance();
        type(widget, "fin");
        press(widget, "Enter");
        expect(widget.getSelectedCodes()).toEqual(["de", "fi"]);
    });

    it("keeps the menu open and the query preselected after a pick", () => {
        const widget = enhance();
        type(widget, "fin");
        press(widget, "Enter");

        // keepInputOnSelection: menu stays open, the picked country is gone
        // from it, and the surviving query text is selected so typing
        // overwrites it.
        expect(widget.menu.hidden).toBe(false);
        expect(widget.input.getAttribute("aria-expanded")).toBe("true");
        expect(widget.input.value).toBe("fin");
        expect(widget.input.selectionStart).toBe(0);
        expect(widget.input.selectionEnd).toBe(3);
        expect(widget.menu.textContent).toContain("No matches");
    });

    it("selects several same-query matches with repeated Enter", () => {
        const widget = enhance();
        // "den" matches both Sweden and Denmark; each pick re-highlights the
        // first remaining match.
        type(widget, "den");
        expect(menuTexts(widget)).toEqual(["Sweden", "Denmark"]);
        press(widget, "Enter");
        press(widget, "Enter");
        expect(widget.getSelectedCodes()).toEqual(["se", "de", "dk"]);
        expect(widget.menu.textContent).toContain("No matches");
    });
});

describe("chip removal", () => {
    it("clicking a chip unchecks the option and fires change", () => {
        const widget = enhance();
        const select = document.getElementById("countries-0");
        const onChange = vi.fn();
        document.getElementById("f").addEventListener("change", onChange);

        widget.root.querySelector('.country-chip[data-code="de"]').click();

        expect(select.querySelector('option[value="de"]').selected).toBe(false);
        expect(chips(widget)).toHaveLength(0);
        expect(onChange).toHaveBeenCalledOnce();
    });

    it("Backspace in an empty input removes the last chip", () => {
        const widget = enhance();
        type(widget, "fin");
        press(widget, "Enter");
        widget.input.value = "";
        press(widget, "Backspace");
        expect(widget.getSelectedCodes()).toEqual(["de"]);
    });

    it("Backspace with text in the input leaves chips alone", () => {
        const widget = enhance();
        type(widget, "fin");
        press(widget, "Backspace");
        expect(widget.getSelectedCodes()).toEqual(["de"]);
    });

    it("removing while the menu is open puts the country back in the menu", () => {
        const widget = enhance();
        press(widget, "ArrowDown");
        expect(menuTexts(widget)).not.toContain("Germany");
        widget.removeCode("de");
        expect(menuTexts(widget)).toContain("Germany");
    });
});

describe("keyboard navigation", () => {
    it("ArrowDown opens the menu and highlights the first option", () => {
        const widget = enhance();
        press(widget, "ArrowDown");
        const first = widget.menu.children[0];
        expect(first.classList.contains("is-highlighted")).toBe(true);
        expect(first.getAttribute("aria-selected")).toBe("true");
        expect(widget.input.getAttribute("aria-activedescendant")).toBe(first.id);
        expect(widget.input.getAttribute("aria-expanded")).toBe("true");
    });

    it("ArrowDown wraps past the end; ArrowUp wraps from the top", () => {
        const widget = enhance();
        press(widget, "ArrowDown"); // open, highlight 0 of 5
        for (let i = 0; i < 5; i++) press(widget, "ArrowDown");
        expect(widget.menu.children[0].classList.contains("is-highlighted")).toBe(true);

        press(widget, "ArrowUp");
        const last = widget.menu.children[widget.menu.children.length - 1];
        expect(last.classList.contains("is-highlighted")).toBe(true);
    });

    it("Escape closes the menu and clears the active descendant", () => {
        const widget = enhance();
        press(widget, "ArrowDown");
        press(widget, "Escape");
        expect(widget.menu.hidden).toBe(true);
        expect(widget.input.getAttribute("aria-expanded")).toBe("false");
        expect(widget.input.hasAttribute("aria-activedescendant")).toBe(false);
    });
});

describe("validity", () => {
    it("mirrors requiredness as a customError on the search input", () => {
        const widget = enhance();
        // One country selected → valid.
        expect(widget.input.checkValidity()).toBe(true);

        widget.removeCode("de");
        expect(widget.input.checkValidity()).toBe(false);
        expect(widget.input.validationMessage).toBe("Select at least one country.");
        expect(document.getElementById("f").checkValidity()).toBe(false);

        type(widget, "swe");
        press(widget, "Enter");
        expect(widget.input.checkValidity()).toBe(true);
        expect(document.getElementById("f").checkValidity()).toBe(true);
    });

    it("leaves a non-required select's input valid while empty", () => {
        const widget = enhance("countries-1");
        expect(widget.getSelectedCodes()).toEqual([]);
        expect(widget.input.checkValidity()).toBe(true);
    });
});
