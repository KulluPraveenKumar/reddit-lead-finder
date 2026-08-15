"""P13 — ``site_signals``: six local signals, read off a website with no model.

The tests here pin the **refusals** as tightly as the matches, because this
module's failure mode is asymmetric. A missed competitor costs one row P14's
model may still find in the prose. A wrong one is seeded into the entity registry
in P15, gains aliases, and matches Reddit posts for the rest of the project's
life — a false fact in the platform's core asset ([AD-13]) is worse than a
missing one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ai.site_signals import (
    SCHEMA_TYPES,
    PricingSignal,
    SiteSignals,
    competitors,
    extract,
    nav_taxonomy,
    pricing,
    social_links,
    structured_data,
    tech_markers,
)
from src.ai.website_fetcher import ExtractedSite, content_hash, extract_text

SITES = Path(__file__).parent / "fixtures" / "sites"
BASE = "https://ledgerloop.example/"


def fixture(name: str) -> str:
    return (SITES / name).read_text(encoding="utf-8")


def a_site(*names: str) -> ExtractedSite:
    """An `ExtractedSite` over the named fixtures, built the way the fetcher does."""
    names = names or ("landing.html", "pricing.html")
    html_pages = tuple((f"/{name}", fixture(name)) for name in names)
    pages = tuple((path, extract_text(html, BASE)) for path, html in html_pages)
    text = "\n\n".join(page_text for _, page_text in pages)
    return ExtractedSite(
        url=BASE,
        pages=pages,
        text=text,
        content_hash=content_hash(text),
        thin=False,
        html_pages=html_pages,
    )


# ------------------------------------------------------------- competitors


class TestCompetitors:
    def test_a_comparison_phrase_names_a_competitor(self):
        assert "Blackline" in competitors("Finance leads evaluating Ledgerloop vs Blackline")

    def test_an_alternative_to_phrase_names_one(self):
        assert "Xero" in competitors("The best alternative to Xero for small teams")

    def test_switching_from_names_one(self):
        assert "QuickBooks" in competitors("Teams switching from QuickBooks tell us")

    def test_the_landing_fixture_yields_the_three_it_names(self):
        found = competitors(extract_text(fixture("landing.html"), BASE))
        assert {"QuickBooks", "Xero", "Blackline"} <= set(found)

    @pytest.mark.parametrize(
        "text",
        [
            "speed vs accuracy in reconciliation",
            "an alternative to spreadsheets",
            "compared to the old way of doing things",
            "accuracy vs the alternative",
        ],
    )
    def test_a_common_noun_after_the_phrase_is_not_a_competitor(self, text):
        """Shipped literally, docs/06 §2.2's `vs\\.?\\s+\\w+` matches *"speed vs
        accuracy"* and seeds *accuracy* into the entity registry. Requiring the
        name to look like a product name misses a genuinely lowercase brand,
        which is the direction this module is supposed to fail in."""
        assert competitors(text) == ()

    def test_a_sentence_initial_capital_is_not_a_competitor(self):
        """Headings and sentence starts make every first word look like a brand."""
        assert competitors("Compared to Our old process, this is faster") == ()

    def test_a_known_name_is_found_by_dictionary(self):
        """The dictionary half of docs/06 §2.2. It is a parameter and not a
        module constant because the dictionary is per project and is built from
        the BKB — which does not exist until P14."""
        assert competitors("We integrate with netsuite daily", known=["NetSuite"]) == ("NetSuite",)

    def test_a_known_name_is_matched_on_word_boundaries(self):
        """A substring search would find *Slack* inside *slackness*."""
        assert competitors("there is some slackness here", known=["Slack"]) == ()

    def test_the_result_is_deduplicated_and_ordered(self):
        found = competitors("vs Xero and later vs Xero again, plus vs Blackline")
        assert found == ("Xero", "Blackline")

    def test_no_competitors_is_an_empty_tuple_not_none(self):
        assert competitors("") == ()


# ----------------------------------------------------------------- pricing


class TestPricing:
    def test_a_dollar_amount_and_its_interval_are_read(self):
        signal = pricing("Plans start at $49 per month for up to three seats.")
        assert "USD" in signal.currencies
        assert "$49" in signal.amounts
        assert "month" in signal.intervals

    def test_other_currencies_are_read_too(self):
        signal = pricing("Annual billing is available at £1,990 per year.")
        assert "GBP" in signal.currencies
        assert "£1,990" in signal.amounts
        assert "year" in signal.intervals

    def test_a_currency_code_is_read_as_well_as_a_symbol(self):
        assert "EUR" in pricing("costs EUR 30 a month").currencies

    def test_posture_is_read_when_there_is_no_number(self):
        """A site with a *Contact sales* tier and no figures still tells you it
        sells to enterprises."""
        signal = pricing("Enterprise: contact sales for a quote.")
        assert signal.amounts == ()
        assert "contact_sales" in signal.posture
        assert signal.has_pricing is True

    def test_a_free_trial_is_posture(self):
        assert "free_trial" in pricing("Every plan starts with a 14-day free trial.").posture

    def test_the_pricing_fixture_yields_all_three_tiers(self):
        signal = pricing(extract_text(fixture("pricing.html"), BASE))
        assert {"$49", "$199"} <= set(signal.amounts)
        assert {"month", "year"} <= set(signal.intervals)
        assert {"contact_sales", "custom", "free_trial"} <= set(signal.posture)

    def test_a_page_with_no_pricing_says_so(self):
        signal = pricing("We reconcile bank statements.")
        assert signal.has_pricing is False

    def test_amounts_stay_strings_beside_their_currency(self):
        """R6 is *categoricals in, arithmetic out*, and this is its input side:
        turning `$49` into `49.0` before anything has decided what the number
        means is how a per-seat monthly price ends up compared against a one-off
        licence fee."""
        signal = pricing("$49 per month")
        assert signal.amounts == ("$49",)
        assert all(isinstance(amount, str) for amount in signal.amounts)

    def test_a_hundred_add_ons_do_not_all_land_in_the_signal(self):
        """A pricing page can list a hundred line items; the first handful
        establishes the posture, which is what P14 asks for."""
        signal = pricing(" ".join(f"${n}0 per month" for n in range(1, 60)))
        assert len(signal.amounts) <= 12

    def test_the_default_signal_is_empty(self):
        assert PricingSignal().has_pricing is False


# ------------------------------------------------------------ tech markers


class TestTechMarkers:
    def test_known_script_hosts_are_named(self):
        found = tech_markers(fixture("landing.html"))
        assert {"Google Tag Manager", "Stripe", "Intercom"} <= set(found)

    def test_an_unknown_host_is_not_guessed_at(self):
        """A dictionary, not a heuristic. Guessing would produce a tech stack
        that is confidently wrong, which is worse than a short one."""
        found = tech_markers(fixture("landing.html"))
        assert not any("example-unknown-vendor" in marker for marker in found)

    def test_the_meta_generator_is_read(self):
        assert "Next.js 14.2" in tech_markers(fixture("landing.html"))

    def test_a_subdomain_of_a_known_host_counts(self):
        html = "<html><head><script src='https://cdn.segment.com/a.js'></script></head></html>"
        assert tech_markers(html) == ("Segment",)

    def test_a_host_that_merely_ends_in_the_same_letters_does_not(self):
        """`notgoogle-analytics.com` is not Google Analytics, and a bare
        `endswith` on the fragment would say it is."""
        html = "<html><head><script src='https://notsegment.com/a.js'></script></head></html>"
        assert tech_markers(html) == ()

    def test_empty_markup_yields_nothing(self):
        assert tech_markers("") == ()


# --------------------------------------------------------- structured data


class TestStructuredData:
    def test_organization_and_product_are_read_from_a_graph(self):
        found = structured_data(fixture("landing.html"))
        types = {node["@type"] for node in found}
        assert {"Organization", "Product"} <= types

    def test_a_nested_offer_is_found(self):
        found = structured_data(fixture("landing.html"))
        assert any(node["@type"] == "Offer" for node in found)

    def test_an_unrelated_type_is_discarded(self):
        """A `BreadcrumbList` is real structured data and tells P14 nothing about
        the business."""
        found = structured_data(fixture("landing.html"))
        assert all(node["@type"] != "BreadcrumbList" for node in found)

    def test_malformed_json_is_skipped_not_raised(self):
        """A broken `ld+json` block is common, entirely the site's business, and
        not a reason to fail an analysis."""
        html = "<html><script type='application/ld+json'>{not json,</script></html>"
        assert structured_data(html) == ()

    def test_a_top_level_array_is_walked(self):
        html = (
            "<html><script type='application/ld+json'>"
            '[{"@type": "Organization", "name": "A"}]'
            "</script></html>"
        )
        assert structured_data(html)[0]["name"] == "A"

    def test_the_three_types_are_the_ones_the_pipeline_document_names(self):
        assert {"Organization", "Product", "Offer"} == SCHEMA_TYPES


# ------------------------------------------------------------ social links


class TestSocialLinks:
    def test_the_communities_the_footer_links_are_found(self):
        found = dict(social_links(fixture("landing.html")))
        assert {"github", "twitter", "linkedin", "hackernews"} <= set(found)

    def test_x_dot_com_is_twitter(self):
        html = "<html><body><a href='https://x.com/ledgerloop'>x</a></body></html>"
        assert social_links(html) == (("twitter", "https://x.com/ledgerloop"),)

    def test_a_www_prefix_does_not_hide_a_platform(self):
        html = "<html><body><a href='https://www.linkedin.com/company/x'>in</a></body></html>"
        assert social_links(html)[0][0] == "linkedin"

    def test_the_order_is_deterministic(self):
        """An unordered set here would make assertions flap between runs for no
        reason a reader could see."""
        html = fixture("landing.html")
        assert social_links(html) == social_links(html)
        assert list(social_links(html)) == sorted(social_links(html))


# ----------------------------------------------------------- nav taxonomy


class TestNavTaxonomy:
    def test_product_vocabulary_is_read_from_the_nav(self):
        found = nav_taxonomy(fixture("landing.html"))
        assert "Bank reconciliation" in found
        assert "Use cases" in found

    def test_site_furniture_is_dropped(self):
        """Keeping *Docs*, *Log in* and *Privacy* would give every business the
        same taxonomy."""
        found = {label.lower() for label in nav_taxonomy(fixture("landing.html"))}
        assert not ({"docs", "log in", "privacy", "security"} & found)

    def test_a_sentence_that_happens_to_be_a_link_is_not_a_label(self):
        html = (
            "<html><footer><a href='/x'>"
            "Read the full story of how we rebuilt our reconciliation engine"
            "</a></footer></html>"
        )
        assert nav_taxonomy(html) == ()

    def test_links_outside_nav_and_footer_are_ignored(self):
        html = "<html><body><a href='/x'>Body link</a></body></html>"
        assert nav_taxonomy(html) == ()


# --------------------------------------------------------------- assembly


class TestExtract:
    def test_all_six_signals_come_back_for_a_real_site(self):
        signals = extract(a_site())
        assert signals.competitors
        assert signals.pricing.has_pricing
        assert signals.tech_markers
        assert signals.structured_data
        assert signals.social_links
        assert signals.nav_taxonomy
        assert signals.markup_seen is True
        assert signals.is_empty is False

    def test_markup_signals_are_read_from_every_page_not_only_the_landing_one(self):
        """A `schema.org` Product block usually sits on `/product`, and the
        pricing page is where the Stripe script is."""
        assert "Segment" in extract(a_site()).tech_markers
        assert "Segment" not in extract(a_site("landing.html")).tech_markers

    def test_a_cache_hit_reports_that_it_saw_no_markup(self):
        """Four of the six signals need HTML, and `website_snapshots` stores only
        text. Returning four empty tuples with no explanation reads identically
        to *"this site has none of these"* — and a consumer that cannot tell
        those apart records "this company uses no analytics" as a fact."""
        cached = ExtractedSite(
            url=BASE,
            pages=(("/", "We are an alternative to Xero. Plans from $49 per month."),),
            text="We are an alternative to Xero. Plans from $49 per month.",
            content_hash="x" * 64,
            thin=False,
            from_cache=True,
            html_pages=(),
        )
        signals = extract(cached)
        assert signals.markup_seen is False
        assert signals.competitors == ("Xero",)
        assert signals.pricing.has_pricing is True
        assert signals.tech_markers == ()
        assert signals.structured_data == ()

    def test_a_thin_site_yields_an_empty_signal_set_without_failing(self):
        html = fixture("spa_shell.html")
        site = ExtractedSite(
            url=BASE,
            pages=(("/", extract_text(html, BASE)),),
            text=extract_text(html, BASE),
            content_hash="y" * 64,
            thin=True,
            html_pages=(("/", html),),
        )
        assert extract(site).is_empty is True

    def test_the_known_dictionary_is_passed_through(self):
        site = ExtractedSite(
            url=BASE,
            pages=(("/", "we replace netsuite"),),
            text="we replace netsuite",
            content_hash="z" * 64,
            thin=False,
            html_pages=(("/", "<html></html>"),),
        )
        assert extract(site, known_competitors=["NetSuite"]).competitors == ("NetSuite",)

    def test_the_default_signal_set_is_empty(self):
        assert SiteSignals().is_empty is True
