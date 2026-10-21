"""UI phase 3a: Home and Procedures. The Home page is Caelza's front door
(status before chat), the upstream dashboard moves to /dashboard with its
deep links forwarded, Procedures fronts the SOP engine, and the Mind's digest
route feeds Home. The pages, the client and the wiring patch stay in step."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
PATCH = (REPO_ROOT / "runtime" / "patches" / "0005-home-procedures.patch").read_text()
API_MIND = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_mind.rs").read_text()
MIND_CLIENT = (OVERLAY / "web" / "src" / "lib" / "mind.ts").read_text()
HOME = (OVERLAY / "web" / "src" / "pages" / "Home.tsx").read_text()
PROCEDURES = (OVERLAY / "web" / "src" / "pages" / "Procedures.tsx").read_text()
QUEUE = (OVERLAY / "web" / "src" / "components" / "ApprovalQueue.tsx").read_text()


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "crates/caelza-gateway/src/lib.rs",
        "web/src/components/CommandPalette.tsx",
        "web/src/components/layout/Header.tsx",
        "web/src/components/layout/Layout.tsx",
        "web/src/components/layout/Sidebar.tsx",
        "web/src/lib/i18n.ts",
        "web/src/router/lazyPages.tsx",
        "web/src/router/router.tsx",
    ]


def test_home_takes_the_root_and_the_dashboard_keeps_its_tabs():
    assert '-        <Route path="/" element={<Dashboard />} />' in PATCH
    assert '+        <Route path="/" element={<Home />} />' in PATCH
    assert '+        <Route path="/dashboard" element={<Dashboard />} />' in PATCH
    assert '+        <Route path="/procedures" element={<Procedures />} />' in PATCH
    # The old `/?tab=` deep links (AgentDrawer, bookmarks) land on the dashboard.
    assert "params.get('tab')" in HOME
    assert "pathname: '/dashboard', search: location.search" in HOME
    # The header and the browser-tab title know the new sections.
    assert "+  '/': 'nav.home'," in PATCH
    for key in ("dashboard: 'nav.dashboard'", "bodies: 'nav.bodies'", "procedures: 'nav.procedures'"):
        assert PATCH.count(f"+  {key},") == 2, key  # Header.tsx and Layout.tsx
    assert "+      name = t('nav.home');" in PATCH
    assert "+    'nav.home': 'Home'," in PATCH and "+    'nav.procedures': 'Procedures'," in PATCH


def test_sidebar_and_palette_follow_the_information_architecture():
    sidebar = PATCH.split("+++ b/web/src/components/layout/Sidebar.tsx")[1].split("+++ b/")[0]
    # The hunks' resulting text (context + added lines): Home first, then Bodies,
    # Memory and Procedures in the Home group, the dashboard leading Operations.
    after = "\n".join(line[1:] for line in sidebar.splitlines() if line.startswith((" ", "+")))
    order = [m.group(1) for m in re.finditer(r"\{ to: '([^']+)'", after)]
    assert order[:5] == ["/", "/bodies", "/memory", "/procedures", "/dashboard"], order
    assert "+      { to: '/dashboard', icon: LayoutDashboard, labelKey: 'nav.dashboard' }," in sidebar
    palette = PATCH.split("+++ b/web/src/components/CommandPalette.tsx")[1].split("+++ b/")[0]
    assert "-  { to: '/', icon: LayoutDashboard, labelKey: 'nav.dashboard'" in palette
    for to in ("/", "/bodies", "/memory", "/procedures", "/dashboard"):
        assert f"+  {{ to: '{to}', icon:" in palette, to


def test_the_digest_route_is_mounted_called_and_guarded():
    assert '+        .route("/api/mind/digest", get(api_mind::handle_mind_digest))' in PATCH
    assert "pub async fn handle_mind_digest" in API_MIND
    assert "/api/mind/digest" in MIND_CLIENT and "getMindDigest" in HOME
    # Status, review, recall, forget, review-decide and digest: six handlers, six auth checks.
    assert API_MIND.count("require_auth(&state, &headers)") == 6
    # The digest reads only; the three brain tools it calls are read-scope.
    digest = API_MIND.split("pub async fn handle_mind_digest")[1].split("pub(crate) fn private_brain")[0]
    assert set(re.findall(r'"(brain_[a-z_]+)"', digest)) == {"brain_status", "brain_commitments", "brain_list_open"}


def test_pages_share_the_approval_queue_and_the_primitives():
    assert "export default function ApprovalQueue" in QUEUE
    assert "decideSop(" in QUEUE and "'approve' : { deny: {} }" in QUEUE
    for page in (HOME, PROCEDURES):
        assert "import ApprovalQueue from '@/components/ApprovalQueue'" in page
        assert "<ApprovalQueue" in page
        assert "cz-eyebrow" in page
        for primitive in ("PageHeader", "Card", "Badge", "Button"):
            assert primitive in page, primitive
    assert "StatCard" in HOME
    # Home links to every top-level section the vision names.
    for to in ("/agents", "/bodies", "/memory", "/procedures", "/dashboard"):
        assert f'to="{to}"' in HOME, to
    # Procedures reaches the SOP engine only through the existing client.
    assert "cancelSop(" in PROCEDURES and "listSops()" in PROCEDURES and "listRuns()" in PROCEDURES
    assert "apiFetch(" not in PROCEDURES and "apiFetch(" not in HOME
