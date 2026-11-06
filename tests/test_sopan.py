import json
from datetime import date
from unittest import mock

import pytest

from sopan import run, telegram as tg
from sopan.core import compile_keywords, extract_links, matches, parse_deadline

LISTING = """
<html><body>
<nav><a href="/">Home</a><a href="/categories/physics">Physics</a></nav>
<ul>
 <li class="card">
   <a href="/job/DTN553/phd-studentship-radio-astronomy">PhD Studentship: Radio Astronomy with LOFAR</a>
   <div>University of Manchester</div><div>Closes 11 Jan</div>
   <a href="/job/DTN553/phd-studentship-radio-astronomy#apply">More</a>
 </li>
 <li class="card">
   <a href="https://www.jobs.ac.uk/job/DTO327/lecturer-in-chemistry">Lecturer in Chemistry</a>
   <div>University of Leeds</div><div>Closes 22 Nov</div>
 </li>
 <li class="card">
   <a href="/job/DTO400/phd-quantum">Funded PhD in Quantum Optics</a>
   <div>University of Bristol</div><div>Application deadline: 2027-02-15</div>
 </li>
</ul></body></html>
"""
BASE = "https://www.jobs.ac.uk/categories/physics"
TODAY = date(2026, 11, 6)


def test_extract_dedupes_and_ignores_nav():
    items = extract_links(LISTING, BASE, "jobs.ac.uk", r"/job/[A-Z]{3}\d{3}")
    assert {i.id for i in items} == {"www.jobs.ac.uk/job/DTN553", "www.jobs.ac.uk/job/DTO327", "www.jobs.ac.uk/job/DTO400"}
    radio = next(i for i in items if "DTN553" in i.id)
    assert radio.title.startswith("PhD Studentship: Radio")
    assert "Closes 11 Jan" in radio.context


def test_context_kept_when_card_has_employer_link():
    html = """<div class="results">
      <div class="card"><a href="/job/AAA111/phd-x">PhD in Galaxy Evolution</a>
        <a href="/employer/durham">Durham University</a><span>Closes 02 Dec</span></div>
      <div class="card"><a href="/job/BBB222/phd-y">PhD in Biology</a><span>Closes 09 Dec</span></div>
    </div>"""
    items = {i.title: i for i in extract_links(html, BASE, "s", r"/job/[A-Z]{3}\d{3}")}
    galaxy = items["PhD in Galaxy Evolution"]
    assert "Durham University" in galaxy.context and "02 Dec" in galaxy.context
    assert "Biology" not in galaxy.context


def test_generic_link_text_uses_url_slug():
    html = '<div><a href="/research/saha-institute-of-nuclear-physics-phd-admission-2027-jan/">View Details</a></div>'
    (item,) = extract_links(html, "https://inphd.com/", "s", r"/research/[a-z0-9-]+")
    assert item.title == "Saha Institute Of Nuclear Physics Phd Admission 2027 Jan"


def test_classify_field():
    from sopan.core import classify_field
    assert classify_field("PhD in Radio Interferometry of Galaxy Clusters") == "Astronomy"
    assert classify_field("Funded PhD in Quantum Optics") == "Quantum"
    assert classify_field("PhD: wind turbine generators") == "Engineering"
    assert classify_field("PhD Studentship: Nonlinear waves on liquid cylinders") == "Physics"


def test_keyword_filter():
    items = extract_links(LISTING, BASE, "s", r"/job/[A-Z]{3}\d{3}")
    phd = compile_keywords(["phd", "studentship"])
    astro = compile_keywords(["astronom", "quantum"])
    kept = [i.title for i in items if matches(i, phd, astro)]
    assert kept == ["PhD Studentship: Radio Astronomy with LOFAR", "Funded PhD in Quantum Optics"]
    # word-start matching: "physic" must not match inside "biophysical"? it should match "physics" only at word start
    assert compile_keywords(["physic"]).search("Biophysical") is None


@pytest.mark.parametrize("text,expected", [
    ("Closes 11 Jan", "2027-01-11"),          # past month in November -> next year
    ("Closes 22 Nov", "2026-11-22"),
    ("Application deadline: 2027-02-15", "2027-02-15"),
    ("Deadline: March 3, 2027", "2027-03-03"),
    ("Apply by 05/12/2026", "2026-12-05"),     # day first
    ("No date here", None),
])
def test_deadlines(text, expected):
    assert parse_deadline(text, TODAY) == expected


def test_chunking_respects_limit():
    blocks = ["x" * 1000] * 9
    msgs = tg.chunk(blocks, "header")
    assert all(len(m) <= tg.LIMIT for m in msgs)
    assert sum(m.count("x" * 1000) for m in msgs) == 9


def test_format_escapes_html():
    it = {"title": "PhD <AI> & Stars", "source": "S", "url": "https://a.b/?x=1&y=2", "deadline": "2026-11-09"}
    out = tg.format_item(it, TODAY)
    assert "&lt;AI&gt; &amp; Stars" in out and "3 days left" in out and "x=1&amp;y=2" in out


def _run_with(tmp_path, html_pages, sent):
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        "keywords:\n  phd: [phd, studentship, doctoral]\n"
        "exclude_titles: ['post-?doc']\n"
        "sources:\n  - name: J\n    url: https://www.jobs.ac.uk/categories/physics\n"
        "    link_pattern: '/job/[A-Z]{3}\\d{3}'\n    match_any: phd\n"
        "watch:\n  - name: Group page\n    url: https://uni.example/group\n"
    )
    pages = iter(html_pages)
    with mock.patch.object(run, "ROOT", tmp_path), \
         mock.patch.object(run, "fetch", lambda url: next(pages)), \
         mock.patch.object(run.time, "sleep", lambda s: None), \
         mock.patch.object(run.tg, "send", lambda t, c, m: sent.append(m)), \
         mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "@c"}):
        assert run.main(["--config", str(cfg)]) == 0


def test_first_run_silent_then_posts_only_new(tmp_path):
    group_v1 = '<a href="/group/people">People of the group</a>'
    group_v2 = group_v1 + '<a href="/group/phd-2027">New PhD position in pulsars</a>'
    sent = []
    _run_with(tmp_path, [LISTING, group_v1], sent)
    assert sent == []  # first scan records, posts nothing
    data = json.loads((tmp_path / "docs" / "data.json").read_text())
    assert len(data["items"]) == 2  # already-open PhDs still show on the web page

    newer = LISTING.replace("</ul>", '<li><a href="/job/DTZ999/phd-cosmology">PhD in Cosmology</a> Closes 1 Dec</li>'
                                     '<li><a href="/job/DTZ998/pd">Post-Doctoral Researcher in Optics</a></li></ul>')
    _run_with(tmp_path, [newer, group_v2], sent)
    text = "\n".join(sent)
    assert "PhD in Cosmology" in text and "Radio Astronomy" not in text
    assert "Post-Doctoral" not in text  # excluded by title
    assert "New PhD position in pulsars" in text and "Watchlist" in text

    sent.clear()
    _run_with(tmp_path, [newer, group_v2], sent)
    assert sent == []  # nothing new, nothing posted


def test_code_titles_and_view_details_prefix():
    html = """<ul>
      <li>University of Geneva, Theoretical Physics, <a href="/ajo/jobs/111">PHDQUANTUM</a> PhD position in quantum theory (deadline 2027/01/15) Apply</li>
      <li><a href="/ajo/jobs/222">ASTRO27PHD</a></li>
    </ul>
    <div><a href="/unijobs/listing/333/x">View details PhD Position on Arctic Energy Budget</a></div>"""
    t = {i.id.split("/")[-1]: i.title for i in extract_links(html, "https://academicjobsonline.org/ajo/physics", "s", r"/(?:ajo/jobs|unijobs/listing)/\d+")}
    assert t["111"] == "University of Geneva, Theoretical Physics, PhD position in quantum theory"
    assert t["222"] == "ASTRO27PHD"   # nothing better available: keep the code
    assert t["333"] == "PhD Position on Arctic Energy Budget"
