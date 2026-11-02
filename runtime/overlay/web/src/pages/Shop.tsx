// The Shop (vision M8): the packs in looks/catalog.json. A free pack joins
// the wardrobe with one tap and its pieces appear in every agent's
// customizer; a "soon" pack is announced; a priced pack takes an unlock code
// (`<PACK>-<ID>-<signature>`, minted by the owner with
// scripts/unlock_codes.py), which the Runtime checks against its public key
// and remembers, so the pack goes back in without a code once opened. The
// wardrobe lives on the Runtime (/api/looks/wardrobe), so it is the same on
// every device.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Check, Clock, KeyRound, Plus, Shirt } from "lucide-react";

import { Badge, Button, PageHeader } from "@/components/ui";
import { getWardrobe, putWardrobe, unlockPack } from "@/lib/api";
import { basePath } from "@/lib/basePath";
import { t } from "@/lib/i18n";
import { catalog } from "@/looks/Look";
import { STARTER, isPriced, ownedPacks, parseUnlockCode, priceLabel, sheetUrl, unlocked, type CatalogPack, type Wardrobe } from "@/looks/looks.logic";

const MUTED = { color: "var(--pc-text-muted)" } as const;

/** The gateway's reason when it gave one, else the error's own words. */
function errorText(e: unknown): string {
  const envelope = (e as { envelope?: { message?: unknown } } | null)?.envelope;
  if (envelope && typeof envelope.message === "string") return envelope.message;
  const text = e instanceof Error ? e.message : String(e);
  // The looks routes answer `{"error": "..."}`, which the client wraps as `API 400: {...}`.
  const wrapped = /^API \d+: (\{[\s\S]*\})$/.exec(text);
  if (wrapped) {
    try {
      const body = JSON.parse(wrapped[1]!) as { error?: unknown; message?: unknown };
      if (typeof body.error === "string") return body.error;
      if (typeof body.message === "string") return body.message;
    } catch {
      /* not JSON after all */
    }
  }
  return text;
}

export default function Shop() {
  const [wardrobe, setWardrobe] = useState<Wardrobe | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [codes, setCodes] = useState<Record<string, string>>({});
  const [attempt, setAttempt] = useState(0);

  // The wardrobe from the Runtime. When it cannot be read, it stays unknown
  // (every Add and Unlock waits on it): an empty stand-in saved by the next
  // tap would overwrite the real one.
  useEffect(() => {
    let cancelled = false;
    getWardrobe()
      .then((w) => {
        if (!cancelled) setWardrobe(w);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorText(e));
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const owned = useMemo(() => ownedPacks(catalog, wardrobe), [wardrobe]);

  const change = async (pack: CatalogPack, add: boolean) => {
    if (busy) return;
    setBusy(pack.id);
    setError(null);
    setNotice(null);
    const current = wardrobe?.packs ?? [];
    const next = add ? [...current.filter((p) => p !== pack.id), pack.id] : current.filter((p) => p !== pack.id);
    try {
      setWardrobe(await putWardrobe({ version: 1, packs: next }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  // A code for a priced pack: its shape is checked here (and which pack it
  // names), its signature on the Runtime, which answers with the wardrobe.
  const unlock = async (pack: CatalogPack) => {
    if (busy) return;
    const code = codes[pack.id] ?? "";
    setError(null);
    setNotice(null);
    const parsed = parseUnlockCode(code);
    if (!parsed) {
      setError(t("shop.code_bad"));
      return;
    }
    if (parsed.pack !== pack.id) {
      const other = catalog.packs.find((p) => p.id === parsed.pack);
      setError(t("shop.code_other_pack").replace("{pack}", other?.name ?? parsed.pack));
      return;
    }
    setBusy(pack.id);
    try {
      setWardrobe(await unlockPack(code));
      setCodes((c) => ({ ...c, [pack.id]: "" }));
      setNotice(t("shop.unlocked"));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <PageHeader
        title={t("shop.title")}
        description={t("shop.description")}
        actions={
          <Link to="/looks">
            <Button variant="ghost" size="sm">
              <Shirt className="h-4 w-4" />
              {t("shop.dress_link")}
            </Button>
          </Link>
        }
      />
      {error ? (
        <div className="text-sm flex items-center gap-3 flex-wrap" role="alert" style={{ color: "var(--color-status-error)" }}>
          <span>
            {t("shop.failed")} {error}
          </span>
          {wardrobe === null ? (
            <button
              type="button"
              className="cz-btn-text"
              onClick={() => {
                setError(null);
                setAttempt((n) => n + 1);
              }}
            >
              {t("shop.retry")}
            </button>
          ) : null}
        </div>
      ) : null}
      {notice ? (
        <div className="text-sm" role="status" style={{ color: "var(--color-status-success)" }}>
          {notice}
        </div>
      ) : null}
      <div className="space-y-4">
        {catalog.packs.map((pack) => {
          const isOwned = owned.has(pack.id);
          const count = catalog.parts.filter((p) => p.pack === pack.id).length;
          return (
            <section key={pack.id} className="card cz-pack">
              <div className="cz-pack-sheet">
                {pack.status === "available" ? (
                  <img src={sheetUrl(basePath, pack.id)} alt="" className="cz-look" loading="lazy" />
                ) : (
                  <div className="cz-pack-soon">
                    <Clock className="h-6 w-6" aria-hidden="true" />
                  </div>
                )}
              </div>
              <div className="cz-pack-body">
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="text-base font-semibold text-pc-text">{pack.name}</h2>
                  <Badge tone={pack.price === "free" ? "ok" : "neutral"}>{pack.price === "free" ? t("shop.free") : priceLabel(pack)}</Badge>
                  {pack.status === "soon" ? <Badge tone="neutral">{t("shop.soon")}</Badge> : null}
                  {count ? (
                    <span className="text-xs" style={MUTED}>
                      {count} {t("shop.pieces")}
                    </span>
                  ) : null}
                </div>
                <p className="text-sm" style={MUTED}>
                  {pack.blurb}
                </p>
                <div className="flex items-center gap-2 flex-wrap">
                  {pack.id === STARTER ? (
                    <Button variant="ghost" size="sm" disabled>
                      <Check className="h-4 w-4" />
                      {t("shop.always_yours")}
                    </Button>
                  ) : pack.status === "soon" ? (
                    <Button variant="ghost" size="sm" disabled>
                      <Clock className="h-4 w-4" />
                      {t("shop.soon")}
                    </Button>
                  ) : isOwned ? (
                    <>
                      <Button variant="ghost" size="sm" disabled>
                        <Check className="h-4 w-4" />
                        {t("shop.in_wardrobe")}
                      </Button>
                      <button type="button" className="cz-btn-text" disabled={busy !== null} onClick={() => void change(pack, false)}>
                        {t("shop.remove")}
                      </button>
                    </>
                  ) : isPriced(pack) && !unlocked(pack.id, wardrobe) ? (
                    <form
                      className="cz-unlock flex items-center gap-2 flex-wrap"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void unlock(pack);
                      }}
                    >
                      <input
                        className="cz-input"
                        style={{ height: 36, width: 220, maxWidth: "100%" }}
                        value={codes[pack.id] ?? ""}
                        onChange={(e) => setCodes((c) => ({ ...c, [pack.id]: e.target.value }))}
                        placeholder={`${pack.id.toUpperCase()}-XXXXXXXX-…`}
                        aria-label={t("shop.code_label")}
                        spellCheck={false}
                        autoComplete="off"
                        disabled={busy !== null || wardrobe === null}
                      />
                      <Button variant="primary" size="sm" type="submit" disabled={busy !== null || wardrobe === null || !(codes[pack.id] ?? "").trim()}>
                        <KeyRound className="h-4 w-4" />
                        {busy === pack.id ? t("shop.unlocking") : t("shop.unlock")}
                      </Button>
                      <span className="text-xs" style={MUTED}>
                        {t("shop.code_hint")}
                        {pack.buy ? (
                          <>
                            {" "}
                            <a className="underline" href={pack.buy} target="_blank" rel="noreferrer">
                              {t("shop.get_code")}
                            </a>
                          </>
                        ) : null}
                      </span>
                    </form>
                  ) : (
                    /* Free, or a priced pack a code opened before: one tap. */
                    <Button variant="primary" size="sm" disabled={busy !== null || wardrobe === null} onClick={() => void change(pack, true)}>
                      <Plus className="h-4 w-4" />
                      {busy === pack.id ? t("shop.adding") : t("shop.add")}
                    </Button>
                  )}
                </div>
              </div>
            </section>
          );
        })}
      </div>
      <div className="text-xs" style={MUTED}>
        {t("shop.updated")} {catalog.updated}.
      </div>
    </div>
  );
}
