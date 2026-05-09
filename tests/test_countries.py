from app.countries import all_countries


class TestAllCountries:
    def test_returns_list_of_tuples(self):
        result = all_countries()
        assert isinstance(result, list)
        assert all(isinstance(item, tuple) and len(item) == 2 for item in result)

    def test_entries_are_str_pairs(self):
        result = all_countries()
        assert all(isinstance(name, str) and isinstance(code, str) for name, code in result)

    def test_codes_are_lowercase_alpha2(self):
        result = all_countries()
        assert all(len(code) == 2 and code.islower() for _, code in result)

    def test_sorted_by_display_name(self):
        result = all_countries()
        names = [name for name, _ in result]
        assert names == sorted(names)

    def test_no_duplicate_codes(self):
        result = all_countries()
        codes = [code for _, code in result]
        assert len(codes) == len(set(codes))

    def test_no_duplicate_names(self):
        result = all_countries()
        names = [name for name, _ in result]
        assert len(names) == len(set(names))

    def test_contains_well_known_countries(self):
        result = all_countries()
        codes = {code for _, code in result}
        for code in ("se", "de", "us", "gb", "fr", "jp"):
            assert code in codes

    def test_uses_friendly_display_names(self):
        # Avoid awkward ISO official names where a common form is widely used.
        result = dict((code, name) for name, code in all_countries())
        assert result["gb"] == "United Kingdom"
        assert result["ru"] == "Russia"
        assert result["kr"] == "South Korea"
        assert result["kp"] == "North Korea"
        assert result["ir"] == "Iran"
        assert result["tw"] == "Taiwan"
