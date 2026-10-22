from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from lxml import etree
from packtools.sps.validation import xml_validations
from packtools.sps.validation.xml_validator_rules import get_default_rules

from collection.models import Language
from issue.models import Issue
from journal.models import Journal, JournalSection
from upload.validation.xml_data_checker import XMLDataChecker


@pytest.mark.django_db
@pytest.mark.parametrize("registered", [True, False])
def test_packtools_checks_issue_and_section_against_registered_journal(registered):
    user = get_user_model().objects.create_user(username="depositor")
    journal = Journal.objects.create(
        creator=user,
        short_title="Test J.",
        nlm_title="Test J" if registered else None,
        license_code="BY",
    )
    issue = Issue.objects.create(creator=user, journal=journal, volume="12", number="1")
    language, _ = Language.objects.get_or_create(code2="en", defaults={"creator": user})
    JournalSection.objects.create(
        creator=user,
        parent=journal,
        language=language,
        text="Research",
        code="research",
    )
    other_journal = Journal.objects.create(creator=user)
    Issue.objects.create(creator=user, journal=other_journal, volume="99", number="1")
    JournalSection.objects.create(
        creator=user,
        parent=other_journal,
        language=language,
        text="Other",
        code="other",
    )
    xml = etree.fromstring(
        b"""<article xml:lang="en" article-type="research-article"
          xmlns:xlink="http://www.w3.org/1999/xlink">
          <front>
            <journal-meta>
              <journal-id journal-id-type="nlm-ta">Test J</journal-id>
              <journal-title-group><journal-title>Test Journal</journal-title></journal-title-group>
            </journal-meta>
            <article-meta>
              <article-categories><subj-group subj-group-type="heading">
                <subject>Research</subject>
              </subj-group></article-categories>
              <title-group><article-title>A study of plants</article-title></title-group>
              <volume>12</volume><issue>1</issue>
              <permissions><license xlink:href="https://creativecommons.org/licenses/by/4.0/"/></permissions>
            </article-meta>
          </front>
        </article>"""
    )
    if not registered:
        xml.find(".//volume").text = "99"
        xml.find(".//subject").text = "Other"
    package = SimpleNamespace(creator=None, xml_with_pre=SimpleNamespace(xmltree=xml))
    checker = XMLDataChecker(package, journal, issue)
    params = get_default_rules()
    params.update(checker.params)

    results = list(xml_validations.validate_bibliographic_strip(xml, params))
    results += list(xml_validations.validate_article_toc_sections(xml, params))
    checked = {
        item["title"]: item
        for item in results
        if item and item["title"] in ("registered issue", "table of contents section")
    }

    assert set(checked) == {"registered issue", "table of contents section"}
    assert all((item["response"] == "OK") == registered for item in checked.values())
    assert checker.params["journal_data"]["abbrev_journal_title"] == journal.short_title
    assert ("nlm_journal_title" in checker.params["journal_data"]) == registered
    license_results = list(xml_validations.validate_open_science_actions(xml, params))
    assert any(
        item
        and item["title"] == "Article license code validation"
        and item["response"] == "OK"
        for item in license_results
    )
